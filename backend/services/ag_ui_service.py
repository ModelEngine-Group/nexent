"""AG-UI protocol adapter for the existing Nexent agent SSE runtime."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from ag_ui.core import (
    ActivityDeltaEvent,
    ActivitySnapshotEvent,
    BaseEvent,
    CustomEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.encoder import EventEncoder
from fastapi import Request
from starlette.responses import StreamingResponse

from consts.model import AgentRequest, HistoryItem, NexentAGUIProps, NexentRunAgentInput
from services.agent_service import run_agent_stream
from services.a2ui_action_service import (
    build_a2ui_action_label,
    release_a2ui_action_reservation,
    validate_a2ui_action_submission,
)
from utils.a2ui_action_utils import (
    build_a2ui_action_query,
    project_a2ui_submission_state,
)
from utils.auth_utils import get_current_user_info

logger = logging.getLogger(__name__)

_REASONING_TYPES = {
    "model_output_thinking",
    "model_output_deep_thinking",
    "model_output_code",
}
_CUSTOM_EVENT_NAMES = {
    "conversation_created": "nexent.conversation.created",
    "search_content": "nexent.source.search",
    "picture_web": "nexent.source.image",
    "token_count": "nexent.token.usage",
    "skill_files": "nexent.attachment",
    "skill_artifact": "nexent.artifact",
    "subagent_start": "nexent.subagent.start",
    "subagent_end": "nexent.subagent.end",
    "agent_new_run": "nexent.agent.run",
    "agent_finish": "nexent.agent.finish",
    "step_count": "nexent.step.count",
    "parse": "nexent.code.parse",
    "memory_search": "nexent.memory.search",
    "verification": "nexent.verification",
    "max_steps_reached": "nexent.max_steps_reached",
    "card": "nexent.card",
    "history_summary": "nexent.history.summary",
    "status": "nexent.stream.status",
}


class AGUIRequestValidationError(ValueError):
    """Raised when AG-UI input attempts to bypass Nexent configuration."""


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    text_parts: list[str] = []
    for part in content:
        if hasattr(part, "model_dump"):
            part = part.model_dump(by_alias=True)
        if isinstance(part, dict) and part.get("type") == "text":
            text_parts.append(str(part.get("text", "")))
    return "".join(text_parts)


def map_run_input_to_agent_request(
    run_input: NexentRunAgentInput,
) -> tuple[AgentRequest, NexentAGUIProps]:
    """Validate AG-UI extensions and map messages to the legacy agent request."""
    if run_input.tools:
        raise AGUIRequestValidationError("Client-provided tools are not supported")
    if run_input.context:
        raise AGUIRequestValidationError("Client-provided context is not supported")
    if run_input.state not in ({}, None):
        raise AGUIRequestValidationError(
            "Client-provided shared state is not supported"
        )

    forwarded = run_input.forwarded_props
    if not isinstance(forwarded, dict) or set(forwarded) != {"nexent"}:
        raise AGUIRequestValidationError(
            "forwardedProps must contain only the nexent object"
        )
    try:
        nexent = NexentAGUIProps.model_validate(forwarded["nexent"])
    except Exception as exc:
        raise AGUIRequestValidationError(
            f"Invalid forwardedProps.nexent: {exc}"
        ) from exc

    conversational: list[tuple[str, str]] = []
    for message in run_input.messages:
        role = getattr(message, "role", "")
        if role not in {"user", "assistant"}:
            continue
        text = _content_to_text(getattr(message, "content", ""))
        if text:
            conversational.append((role, text))

    if nexent.a2ui_action is not None:
        query = build_a2ui_action_query(
            nexent.a2ui_action.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        if conversational and conversational[-1][0] == "user":
            conversational = conversational[:-1]
    elif nexent.resume:
        if nexent.conversation_id is None:
            raise AGUIRequestValidationError(
                "resume requires an existing conversationId"
            )
        query = next(
            (content for role, content in reversed(conversational) if role == "user"),
            "[resume]",
        )
        conversational = []
    else:
        if not conversational or conversational[-1][0] != "user":
            raise AGUIRequestValidationError("messages must end with a user message")
        query = conversational[-1][1]
        conversational = conversational[:-1]

    history = [
        HistoryItem(role=role, content=content) for role, content in conversational
    ]
    capability = nexent.capabilities.a2ui
    a2ui_client_enabled = bool(
        capability
        and "v0.9" in capability.versions
        and capability.catalog_id == "nexent.v1"
    )
    return AgentRequest(
        query=query,
        conversation_id=nexent.conversation_id,
        history=history,
        minio_files=nexent.minio_files,
        agent_id=nexent.agent_id,
        model_id=nexent.model_id,
        requested_output_tokens=nexent.requested_output_tokens,
        version_no=nexent.version_no,
        is_debug=nexent.is_debug,
        tool_params=nexent.tool_params,
        context_policy=nexent.context_policy,
        enable_plan=nexent.enable_plan,
        a2ui_client_enabled=a2ui_client_enabled,
        a2ui_surface_id=None,
        persisted_query=None,
        server_side_message_index=True,
    ), nexent


def _decode_content(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


class AGUIEventAdapter:
    """Stateful mapper that preserves AG-UI message boundary ordering."""

    def __init__(self, thread_id: str, run_id: str):
        self.thread_id = thread_id
        self.run_id = run_id
        self.reasoning_id: str | None = None
        self.text_id: str | None = None
        self.plan_id = f"{run_id}:plan"
        self.counter = 0
        self.failed = False

    def _next_id(self, kind: str) -> str:
        self.counter += 1
        return f"{self.run_id}:{kind}:{self.counter}"

    def _close_reasoning(self) -> list[BaseEvent]:
        if self.reasoning_id is None:
            return []
        event = ReasoningMessageEndEvent(messageId=self.reasoning_id)
        self.reasoning_id = None
        return [event]

    def _close_text(self) -> list[BaseEvent]:
        if self.text_id is None:
            return []
        event = TextMessageEndEvent(messageId=self.text_id)
        self.text_id = None
        return [event]

    def close_messages(self) -> list[BaseEvent]:
        return [*self._close_reasoning(), *self._close_text()]

    def map_payload(self, payload: dict[str, Any]) -> list[BaseEvent]:
        chunk_type = str(payload.get("type") or "")
        content = payload.get("content", "")

        if chunk_type in _REASONING_TYPES:
            events = self._close_text()
            if self.reasoning_id is None:
                self.reasoning_id = self._next_id("reasoning")
                events.append(
                    ReasoningMessageStartEvent(
                        messageId=self.reasoning_id, role="reasoning"
                    )
                )
            if content:
                events.append(
                    ReasoningMessageContentEvent(
                        messageId=self.reasoning_id, delta=str(content)
                    )
                )
            return events

        if chunk_type == "final_answer":
            events = self._close_reasoning()
            if self.text_id is None:
                self.text_id = self._next_id("message")
                events.append(
                    TextMessageStartEvent(messageId=self.text_id, role="assistant")
                )
            if content:
                events.append(
                    TextMessageContentEvent(messageId=self.text_id, delta=str(content))
                )
            return events

        events = self.close_messages()

        if chunk_type in {"tool", "tool-call"}:
            tool_call_id = str(payload.get("tool_call_id") or self._next_id("tool"))
            tool_name = str(payload.get("tool_name") or "nexent_tool")
            arguments = payload.get("tool_arguments")
            if arguments is None:
                arguments = _decode_content(content) if content else {}
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            events.extend(
                [
                    ToolCallStartEvent(toolCallId=tool_call_id, toolCallName=tool_name),
                    ToolCallArgsEvent(toolCallId=tool_call_id, delta=arguments),
                    ToolCallEndEvent(toolCallId=tool_call_id),
                ]
            )
            return events

        if chunk_type == "execution_logs":
            if payload.get("tool_call_id"):
                events.append(
                    ToolCallResultEvent(
                        messageId=self._next_id("tool-result"),
                        toolCallId=str(payload["tool_call_id"]),
                        content=str(content),
                        role="tool",
                    )
                )
            return events

        if chunk_type == "plan":
            events.append(
                ActivitySnapshotEvent(
                    messageId=self.plan_id,
                    activityType="nexent.plan",
                    content=_decode_content(content),
                )
            )
            return events

        if chunk_type == "plan_step_update":
            events.append(
                ActivityDeltaEvent(
                    messageId=self.plan_id,
                    activityType="nexent.plan",
                    patch=[
                        {
                            "op": "add",
                            "path": "/updates/-",
                            "value": _decode_content(content),
                        }
                    ],
                )
            )
            return events

        if chunk_type == "a2ui":
            events.append(
                CustomEvent(name="nexent.a2ui", value=_decode_content(content))
            )
            return events

        if chunk_type == "error":
            self.failed = True
            events.append(
                RunErrorEvent(
                    message=str(content) or "Agent run failed",
                    code="NEXENT_AGENT_ERROR",
                )
            )
            return events

        custom_name = _CUSTOM_EVENT_NAMES.get(chunk_type)
        if custom_name:
            value = _decode_content(content)
            metadata = {
                key: item
                for key, item in payload.items()
                if key not in {"type", "content"}
            }
            if isinstance(value, dict):
                value = {**value, **metadata}
            elif isinstance(value, list):
                value = [
                    {**item, **metadata} if isinstance(item, dict) else item
                    for item in value
                ]
            events.append(CustomEvent(name=custom_name, value=value))
            return events

        if chunk_type:
            events.append(
                CustomEvent(
                    name=f"nexent.{chunk_type.replace('_', '.')}", value=payload
                )
            )
        return events

    def finish(self) -> list[BaseEvent]:
        events = self.close_messages()
        if not self.failed:
            events.append(RunFinishedEvent(threadId=self.thread_id, runId=self.run_id))
        return events


async def _iter_legacy_payloads(
    body_iterator: AsyncIterator[Any],
) -> AsyncIterator[dict[str, Any]]:
    """Decode complete data fields from an arbitrarily chunked SSE body."""
    buffer = ""
    async for chunk in body_iterator:
        buffer += chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
        buffer = buffer.replace("\r\n", "\n")
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            data_lines = [
                line[5:].lstrip()
                for line in block.splitlines()
                if line.startswith("data:")
            ]
            if not data_lines:
                continue
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                logger.warning("Ignoring malformed legacy SSE payload")
                continue
            if isinstance(payload, dict):
                if "status" in payload and "type" not in payload:
                    payload = {
                        "type": "status",
                        "content": payload["status"],
                        **payload,
                    }
                yield payload

    if buffer.strip():
        data_lines = [
            line[5:].lstrip()
            for line in buffer.splitlines()
            if line.startswith("data:")
        ]
        if data_lines:
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                return
            if isinstance(payload, dict):
                yield payload


async def run_agent_agui_stream(
    run_input: NexentRunAgentInput,
    http_request: Request,
    authorization: str | None,
) -> StreamingResponse:
    """Run the legacy Nexent agent and expose its output as standard AG-UI SSE."""
    agent_request, nexent = map_run_input_to_agent_request(run_input)
    validated_action = None
    submitted_form_state = None
    if nexent.a2ui_action is not None:
        user_id, _, language = get_current_user_info(authorization, http_request)
        validated_action = validate_a2ui_action_submission(
            nexent.a2ui_action,
            conversation_id=agent_request.conversation_id,
            user_id=user_id,
        )
        agent_request = agent_request.model_copy(
            update={
                "query": build_a2ui_action_query(validated_action.payload),
                "a2ui_action_payload": validated_action.payload,
                "persisted_query": build_a2ui_action_label(
                    validated_action,
                    action_name=nexent.a2ui_action.message.action.name,
                    language=language,
                ),
            }
        )
        submitted_form_state = project_a2ui_submission_state(validated_action.payload)
    startup_error: Exception | None = None
    try:
        legacy_response = await run_agent_stream(
            agent_request=agent_request,
            http_request=http_request,
            authorization=authorization,
            resume=nexent.resume,
        )
    except Exception as exc:
        action_persisted = bool(
            validated_action is not None
            and agent_request.a2ui_action_persisted
        )
        if validated_action is not None and not action_persisted:
            release_a2ui_action_reservation(validated_action)
        if not action_persisted:
            raise
        logger.exception("Agent setup failed after A2UI action persistence")
        startup_error = exc
        legacy_response = None
    encoder = EventEncoder()

    async def event_stream() -> AsyncIterator[str]:
        adapter = AGUIEventAdapter(run_input.thread_id, run_input.run_id)
        yield encoder.encode(
            RunStartedEvent(
                threadId=run_input.thread_id,
                runId=run_input.run_id,
                parentRunId=run_input.parent_run_id,
            )
        )
        if submitted_form_state is not None:
            yield encoder.encode(
                CustomEvent(
                    name="nexent.a2ui.form.submitted",
                    value=submitted_form_state,
                )
            )
        if startup_error is not None:
            adapter.failed = True
            yield encoder.encode(
                RunErrorEvent(
                    message="Agent run failed after accepting the action",
                    code="NEXENT_AGENT_ERROR",
                )
            )
            return
        try:
            if isinstance(legacy_response, StreamingResponse):
                async for payload in _iter_legacy_payloads(
                    legacy_response.body_iterator
                ):
                    for event in adapter.map_payload(payload):
                        yield encoder.encode(event)
            else:
                body = getattr(legacy_response, "body", b"")
                value = json.loads(body.decode("utf-8")) if body else {}
                yield encoder.encode(
                    CustomEvent(name="nexent.stream.status", value=value)
                )
        except Exception:
            logger.exception("AG-UI stream adaptation failed")
            for event in adapter.close_messages():
                yield encoder.encode(event)
            adapter.failed = True
            yield encoder.encode(
                RunErrorEvent(
                    message="Agent stream encoding failed", code="NEXENT_AGUI_ERROR"
                )
            )
        for event in adapter.finish():
            yield encoder.encode(event)

    headers = {"Cache-Control": "no-cache", "Connection": "keep-alive"}
    if agent_request.conversation_id is not None:
        headers["conversation_id"] = str(agent_request.conversation_id)
    return StreamingResponse(
        event_stream(), media_type=encoder.get_content_type(), headers=headers
    )
