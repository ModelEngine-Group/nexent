"""Minimal AG-UI adapter for the existing Nexent agent stream."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from ag_ui.core import (
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

logger = logging.getLogger(__name__)

A2UI_BASIC_CATALOG_ID = "https://a2ui.org/specification/v0_9/basic_catalog.json"
_REASONING_TYPES = {
    "model_output_thinking",
    "model_output_deep_thinking",
    "model_output_code",
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
    """Validate AG-UI extensions and map messages to the legacy request."""
    if run_input.tools:
        raise AGUIRequestValidationError("Client-provided tools are not supported")
    if run_input.context:
        raise AGUIRequestValidationError("Client-provided context is not supported")
    if run_input.state not in ({}, None):
        raise AGUIRequestValidationError("Client-provided shared state is not supported")

    forwarded = run_input.forwarded_props
    if not isinstance(forwarded, dict) or set(forwarded) != {"nexent"}:
        raise AGUIRequestValidationError("forwardedProps must contain only the nexent object")
    try:
        nexent = NexentAGUIProps.model_validate(forwarded["nexent"])
    except Exception as exc:
        raise AGUIRequestValidationError(f"Invalid forwardedProps.nexent: {exc}") from exc

    conversational: list[tuple[str, str]] = []
    for message in run_input.messages:
        role = getattr(message, "role", "")
        if role not in {"user", "assistant"}:
            continue
        text = _content_to_text(getattr(message, "content", ""))
        if text:
            conversational.append((role, text))

    if nexent.resume:
        if nexent.conversation_id is None:
            raise AGUIRequestValidationError("resume requires an existing conversationId")
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

    capability = nexent.capabilities.a2ui
    a2ui_client_enabled = bool(
        capability
        and "v0.9" in capability.versions
        and capability.catalog_id == A2UI_BASIC_CATALOG_ID
    )
    history = [HistoryItem(role=role, content=content) for role, content in conversational]
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
        a2ui_action=nexent.a2ui_action,
    ), nexent


def _decode_content(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


class AGUIEventAdapter:
    """Map the core Nexent SSE events to ordered AG-UI events."""

    def __init__(self, thread_id: str, run_id: str):
        self.thread_id = thread_id
        self.run_id = run_id
        self.reasoning_id: str | None = None
        self.text_id: str | None = None
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
                events.append(ReasoningMessageStartEvent(messageId=self.reasoning_id, role="reasoning"))
            if content:
                events.append(ReasoningMessageContentEvent(messageId=self.reasoning_id, delta=str(content)))
            return events

        if chunk_type == "final_answer":
            events = self._close_reasoning()
            if self.text_id is None:
                self.text_id = self._next_id("message")
                events.append(TextMessageStartEvent(messageId=self.text_id, role="assistant"))
            if content:
                events.append(TextMessageContentEvent(messageId=self.text_id, delta=str(content)))
            return events

        if chunk_type in {"tool", "tool-call"}:
            events = self.close_messages()
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

        if chunk_type == "execution_logs" and payload.get("tool_call_id"):
            events = self.close_messages()
            events.append(
                ToolCallResultEvent(
                    messageId=self._next_id("tool-result"),
                    toolCallId=str(payload["tool_call_id"]),
                    content=str(content),
                    role="tool",
                )
            )
            return events

        if chunk_type == "a2ui":
            events = self.close_messages()
            events.append(CustomEvent(name="nexent.a2ui", value=_decode_content(content)))
            return events

        if chunk_type == "conversation_created":
            events = self.close_messages()
            events.append(CustomEvent(name="nexent.conversation.created", value=_decode_content(content)))
            return events

        if chunk_type == "error":
            events = self.close_messages()
            self.failed = True
            events.append(RunErrorEvent(message=str(content) or "Agent run failed", code="NEXENT_AGENT_ERROR"))
            return events
        return []

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
            data_lines = [line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")]
            if not data_lines:
                continue
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                logger.warning("Ignoring malformed legacy SSE payload")
                continue
            if isinstance(payload, dict):
                yield payload

    if buffer.strip():
        data_lines = [line[5:].lstrip() for line in buffer.splitlines() if line.startswith("data:")]
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
    """Run the existing Nexent agent and encode its stream as AG-UI SSE."""
    agent_request, nexent = map_run_input_to_agent_request(run_input)
    legacy_response = await run_agent_stream(
        agent_request=agent_request,
        http_request=http_request,
        authorization=authorization,
        resume=nexent.resume,
    )
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
        try:
            if isinstance(legacy_response, StreamingResponse):
                async for payload in _iter_legacy_payloads(legacy_response.body_iterator):
                    for event in adapter.map_payload(payload):
                        yield encoder.encode(event)
            else:
                adapter.failed = True
                yield encoder.encode(
                    RunErrorEvent(message="Agent stream is unavailable", code="NEXENT_AGUI_ERROR")
                )
        except Exception:
            logger.exception("AG-UI stream adaptation failed")
            for event in adapter.close_messages():
                yield encoder.encode(event)
            adapter.failed = True
            yield encoder.encode(
                RunErrorEvent(message="Agent stream encoding failed", code="NEXENT_AGUI_ERROR")
            )
        for event in adapter.finish():
            yield encoder.encode(event)

    headers = {"Cache-Control": "no-cache", "Connection": "keep-alive"}
    if agent_request.conversation_id is not None:
        headers["conversation_id"] = str(agent_request.conversation_id)
    return StreamingResponse(event_stream(), media_type=encoder.get_content_type(), headers=headers)
