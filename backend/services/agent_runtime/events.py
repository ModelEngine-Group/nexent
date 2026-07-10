"""Runtime event contracts and legacy observer bridge helpers."""

from __future__ import annotations

import inspect
import json
from collections import deque
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_SAFE_RUNTIME_ERROR_MESSAGE = "Agent execution failed. Please try again later."


class RuntimeEventType(str, Enum):
    """Framework-neutral event types emitted by runtime adapters."""

    RUN = "run"
    STEP = "step"
    MODEL_INPUT = "model_input"
    MODEL_OUTPUT = "model_output"
    MODEL_DELTA = "model_delta"
    MODEL_REASONING = "model_reasoning"
    TOOL_CALL = "tool_call"
    TOOL_DISPLAY = "tool_display"
    RETRIEVAL = "retrieval"
    IMAGE = "image"
    ARTIFACT_CREATED = "artifact_created"
    TOKEN_COUNT = "token_count"
    VERIFICATION = "verification"
    MAX_STEPS = "max_steps"
    SUB_AGENT = "sub_agent"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"
    RUN_FINISHED = "run_finished"
    LEGACY_PROCESS = "legacy_process"


MERGEABLE_LEGACY_PROCESS_TYPES = {
    "model_output_code",
    "model_output_thinking",
    "model_output_deep_thinking",
}

LEGACY_PROCESS_TYPES = {
    "agent_new_run",
    "agent_finish",
    "card",
    "error",
    "execution_logs",
    "final_answer",
    "max_steps_reached",
    "memory_search",
    "model_output_code",
    "model_output_deep_thinking",
    "model_output_thinking",
    "other",
    "parse",
    "picture_web",
    "search_content",
    "step_count",
    "token_count",
    "tool",
    "verification",
}

SMOLAGENTS_PROCESS_TYPE_COMPATIBILITY = {
    process_type: "complete"
    for process_type in sorted(LEGACY_PROCESS_TYPES)
}


class RuntimeEvent(BaseModel):
    """A single normalized runtime event before SSE or persistence mapping."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: RuntimeEventType
    request_id: str | None = None
    sequence: int | None = None
    agent_name: str | None = None
    step_number: int | None = None
    content: Any | None = None
    delta: str | None = None
    reasoning: str | None = None
    tool_name: str | None = None
    tool_input: Any | None = None
    tool_output: Any | None = None
    artifact: dict[str, Any] | None = None
    token_usage: dict[str, Any] | None = None
    error: str | None = None
    compat_process_type: str | None = None
    unit_merge_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeProcessPayload(BaseModel):
    """Legacy ProcessType payload plus internal merge metadata."""

    process_type: str
    content: Any = ""
    unit_merge_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_sse_payload(self) -> dict[str, Any]:
        """Return the existing SSE-compatible payload shape."""
        return {
            "type": self.process_type,
            "content": self.content,
        }


class RuntimeDeliveryItem(BaseModel):
    """Prepared API-layer delivery actions for a runtime event."""

    event: RuntimeEvent
    process_payload: RuntimeProcessPayload
    sse_payload: dict[str, Any]
    message_unit: dict[str, Any] | None = None
    skill_file_uploads: list[dict[str, Any]] = Field(default_factory=list)
    skill_file_attachments: list[dict[str, Any]] = Field(default_factory=list)
    monitoring_metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeEventSink:
    """In-memory ordered sink used by runtime adapters and API-layer tests."""

    def __init__(self, request_id: str | None = None):
        self.request_id = request_id
        self._events: list[RuntimeEvent] = []
        self._queue: deque[RuntimeEvent] = deque()
        self._next_sequence = 0

    @property
    def events(self) -> tuple[RuntimeEvent, ...]:
        """Return an immutable snapshot of delivered events."""
        return tuple(self._events)

    def emit(self, event: RuntimeEvent) -> RuntimeEvent:
        """Record one event and assign request/sequence metadata when absent."""
        if event.request_id is None and self.request_id is not None:
            event = event.model_copy(update={"request_id": self.request_id})
        if event.sequence is None:
            event = event.model_copy(update={"sequence": self._next_sequence})
        self._next_sequence = max(self._next_sequence, int(event.sequence) + 1)
        self._events.append(event)
        self._queue.append(event)
        return event

    async def emit_async(self, event: RuntimeEvent) -> RuntimeEvent:
        """Async-compatible wrapper for runtime code paths."""
        return self.emit(event)

    def drain(self) -> list[RuntimeEvent]:
        """Return and clear queued events while keeping the historical snapshot."""
        drained = list(self._queue)
        self._queue.clear()
        return drained


async def emit_runtime_event(event_sink: Any, event: RuntimeEvent) -> RuntimeEvent | None:
    """Emit an event to a sink that may expose sync or async emit methods."""
    if event_sink is None:
        return None
    emit = getattr(event_sink, "emit", None)
    if not callable(emit):
        return None
    result = emit(event)
    if inspect.isawaitable(result):
        result = await result
    return result


def runtime_event_from_legacy_observer_message(
    message: Any,
    *,
    request_id: str | None = None,
    agent_name: str | None = None,
) -> RuntimeEvent:
    """Convert current MessageObserver JSON output into a RuntimeEvent."""
    payload = _parse_legacy_observer_message(message)
    compat_process_type = str(payload.get("type") or "other")
    content = payload.get("content")
    return RuntimeEvent(
        type=RuntimeEventType.LEGACY_PROCESS,
        request_id=request_id,
        agent_name=agent_name,
        content=content,
        compat_process_type=compat_process_type,
        unit_merge_key=_legacy_unit_merge_key(compat_process_type),
        payload=payload,
    )


def runtime_event_to_process_payload(
    event: RuntimeEvent,
    *,
    safe_error_message: str = DEFAULT_SAFE_RUNTIME_ERROR_MESSAGE,
) -> RuntimeProcessPayload:
    """Map RuntimeEvent to the current ProcessType-compatible payload."""
    if event.type == RuntimeEventType.LEGACY_PROCESS:
        return RuntimeProcessPayload(
            process_type=event.compat_process_type or "other",
            content=event.content if event.content is not None else "",
            unit_merge_key=event.unit_merge_key,
            metadata={"runtime_event_type": event.type.value},
        )

    if event.type == RuntimeEventType.RUN:
        return RuntimeProcessPayload(
            process_type=event.compat_process_type or "agent_new_run",
            content=event.content if event.content is not None else event.payload,
            metadata={"runtime_event_type": event.type.value, **event.metadata},
        )

    if event.type == RuntimeEventType.RUN_FINISHED:
        return RuntimeProcessPayload(
            process_type=event.compat_process_type or "agent_finish",
            content=event.content if event.content is not None else event.payload,
            metadata={"runtime_event_type": event.type.value, **event.metadata},
        )

    if event.type == RuntimeEventType.STEP:
        return RuntimeProcessPayload(
            process_type=event.compat_process_type or "step_count",
            content=event.content if event.content is not None else event.payload,
            metadata={"runtime_event_type": event.type.value, **event.metadata},
        )

    if event.type in {RuntimeEventType.MODEL_OUTPUT, RuntimeEventType.MODEL_DELTA}:
        content = event.delta if event.delta is not None else event.content
        return RuntimeProcessPayload(
            process_type=event.compat_process_type or "model_output_thinking",
            content=content if content is not None else "",
            unit_merge_key=event.unit_merge_key or "runtime:model_output_thinking",
            metadata={"runtime_event_type": event.type.value, **event.metadata},
        )

    if event.type == RuntimeEventType.MODEL_REASONING:
        content = event.reasoning if event.reasoning is not None else event.content
        return RuntimeProcessPayload(
            process_type=event.compat_process_type or "model_output_deep_thinking",
            content=content if content is not None else "",
            unit_merge_key=event.unit_merge_key or "runtime:model_output_deep_thinking",
            metadata={"runtime_event_type": event.type.value, **event.metadata},
        )

    if event.type == RuntimeEventType.TOOL_CALL:
        content = event.content
        if content is None:
            content = {
                "tool_name": event.tool_name,
                "tool_input": event.tool_input,
                "tool_output": event.tool_output,
                **event.payload,
            }
        return RuntimeProcessPayload(
            process_type=event.compat_process_type or "tool",
            content=content,
            metadata={"runtime_event_type": event.type.value, **event.metadata},
        )

    if event.type == RuntimeEventType.TOOL_DISPLAY:
        return RuntimeProcessPayload(
            process_type=event.compat_process_type or "card",
            content=event.content if event.content is not None else event.payload,
            metadata={"runtime_event_type": event.type.value, **event.metadata},
        )

    if event.type == RuntimeEventType.RETRIEVAL:
        return RuntimeProcessPayload(
            process_type=event.compat_process_type or "search_content",
            content=event.content if event.content is not None else event.payload,
            metadata={"runtime_event_type": event.type.value, **event.metadata},
        )

    if event.type == RuntimeEventType.IMAGE:
        return RuntimeProcessPayload(
            process_type=event.compat_process_type or "picture_web",
            content=event.content if event.content is not None else event.payload,
            metadata={"runtime_event_type": event.type.value, **event.metadata},
        )

    if event.type == RuntimeEventType.FINAL_ANSWER:
        return RuntimeProcessPayload(
            process_type="final_answer",
            content=event.content if event.content is not None else "",
            metadata={"runtime_event_type": event.type.value},
        )

    if event.type == RuntimeEventType.ERROR:
        safe_content = (
            event.metadata.get("safe_content")
            or event.payload.get("safe_content")
            or safe_error_message
        )
        return RuntimeProcessPayload(
            process_type="error",
            content=safe_content,
            metadata={
                "runtime_event_type": event.type.value,
                "raw_error": event.error or event.content,
            },
        )

    if event.type == RuntimeEventType.TOKEN_COUNT:
        content = event.content
        if content is None:
            content = json.dumps(event.token_usage or event.payload, ensure_ascii=False)
        return RuntimeProcessPayload(
            process_type="token_count",
            content=content,
            metadata={"runtime_event_type": event.type.value},
        )

    if event.type == RuntimeEventType.ARTIFACT_CREATED:
        artifact_payload = event.artifact or event.payload
        return RuntimeProcessPayload(
            process_type="skill_files",
            content=json.dumps(
                {"skill_file_uploads": [artifact_payload] if artifact_payload else []},
                ensure_ascii=False,
            ),
            metadata={"runtime_event_type": event.type.value},
        )

    if event.type == RuntimeEventType.MAX_STEPS:
        return RuntimeProcessPayload(
            process_type="max_steps_reached",
            content=event.content if event.content is not None else event.payload,
            metadata={"runtime_event_type": event.type.value},
        )

    if event.type == RuntimeEventType.VERIFICATION:
        return RuntimeProcessPayload(
            process_type="verification",
            content=event.content if event.content is not None else event.payload,
            metadata={"runtime_event_type": event.type.value},
        )

    return RuntimeProcessPayload(
        process_type="other",
        content=event.content if event.content is not None else event.payload,
        metadata={"runtime_event_type": event.type.value},
    )


def runtime_events_to_delivery_items(
    events: list[RuntimeEvent] | tuple[RuntimeEvent, ...],
    *,
    starting_unit_index: int = 0,
) -> list[RuntimeDeliveryItem]:
    """Prepare ordered SSE, persistence and monitoring actions for events."""
    items: list[RuntimeDeliveryItem] = []
    next_unit_index = starting_unit_index
    current_merge_key: str | None = None
    current_merge_unit_index: int | None = None
    for event in events:
        process_payload = runtime_event_to_process_payload(event)
        sse_payload = process_payload.to_sse_payload()
        if (
            process_payload.unit_merge_key
            and process_payload.unit_merge_key == current_merge_key
            and current_merge_unit_index is not None
        ):
            unit_index = current_merge_unit_index
        else:
            unit_index = next_unit_index
            current_merge_key = process_payload.unit_merge_key
            current_merge_unit_index = unit_index if process_payload.unit_merge_key else None
            next_unit_index += 1
        message_unit = _message_unit_for_payload(process_payload, unit_index)

        skill_file_uploads = _skill_file_uploads_for_payload(process_payload)
        items.append(
            RuntimeDeliveryItem(
                event=event,
                process_payload=process_payload,
                sse_payload=sse_payload,
                message_unit=message_unit,
                skill_file_uploads=skill_file_uploads,
                skill_file_attachments=[
                    _skill_file_upload_to_attachment(upload)
                    for upload in skill_file_uploads
                ],
                monitoring_metadata={
                    "runtime_event_type": event.type.value,
                    "runtime_event_sequence": event.sequence,
                    "runtime_request_id": event.request_id,
                    **event.metadata,
                },
            )
        )
    return items


def _message_unit_for_payload(
    process_payload: RuntimeProcessPayload,
    unit_index: int,
) -> dict[str, Any] | None:
    if process_payload.process_type == "skill_files":
        return None
    return {
        "type": process_payload.process_type,
        "content": process_payload.content,
        "unit_index": unit_index,
        "unit_merge_key": process_payload.unit_merge_key,
    }


def _skill_file_uploads_for_payload(
    process_payload: RuntimeProcessPayload,
) -> list[dict[str, Any]]:
    if process_payload.process_type != "skill_files":
        return []
    if isinstance(process_payload.content, str):
        try:
            payload = json.loads(process_payload.content)
        except json.JSONDecodeError:
            return []
    elif isinstance(process_payload.content, dict):
        payload = process_payload.content
    else:
        return []
    uploads = payload.get("skill_file_uploads", [])
    if not isinstance(uploads, list):
        return []
    return [dict(upload) for upload in uploads if isinstance(upload, dict)]


def _skill_file_upload_to_attachment(upload: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_name": upload.get("object_name", ""),
        "name": upload.get("file_name", upload.get("name", "")),
        "type": "file",
        "size": upload.get("file_size", upload.get("size", 0)),
        "url": upload.get("url", ""),
        "presigned_url": upload.get("presigned_url", upload.get("preview_url", "")),
        "description": "",
    }


def _parse_legacy_observer_message(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return dict(message)
    if isinstance(message, str):
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError:
            return {"type": "other", "content": message}
        if isinstance(parsed, dict):
            return parsed
    return {"type": "other", "content": message}


def _legacy_unit_merge_key(compat_process_type: str) -> str | None:
    if compat_process_type in MERGEABLE_LEGACY_PROCESS_TYPES:
        return f"legacy:{compat_process_type}"
    return None
