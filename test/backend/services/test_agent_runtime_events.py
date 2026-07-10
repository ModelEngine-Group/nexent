import json
import os
import re
import sys
from pathlib import Path

import pytest

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from services.agent_runtime.events import (
    DEFAULT_SAFE_RUNTIME_ERROR_MESSAGE,
    RuntimeEvent,
    RuntimeEventSink,
    RuntimeEventType,
    SMOLAGENTS_PROCESS_TYPE_COMPATIBILITY,
    emit_runtime_event,
    runtime_event_from_legacy_observer_message,
    runtime_event_to_process_payload,
    runtime_events_to_delivery_items,
)


def test_runtime_event_sink_preserves_delivery_order_and_assigns_sequence():
    sink = RuntimeEventSink(request_id="req-1")

    first = sink.emit(RuntimeEvent(type=RuntimeEventType.RUN, content="start"))
    second = sink.emit(RuntimeEvent(type=RuntimeEventType.STEP, content={"step": 1}))

    assert first.request_id == "req-1"
    assert first.sequence == 0
    assert second.request_id == "req-1"
    assert second.sequence == 1
    assert [event.type for event in sink.events] == [
        RuntimeEventType.RUN,
        RuntimeEventType.STEP,
    ]
    assert sink.drain() == [first, second]
    assert sink.drain() == []
    assert sink.events == (first, second)


@pytest.mark.asyncio
async def test_emit_runtime_event_supports_sync_and_async_sinks():
    sync_sink = RuntimeEventSink(request_id="sync")
    sync_event = RuntimeEvent(type=RuntimeEventType.FINAL_ANSWER, content="done")

    assert await emit_runtime_event(sync_sink, sync_event) == sync_sink.events[0]

    class AsyncSink:
        def __init__(self):
            self.events = []

        async def emit(self, event):
            self.events.append(event)
            return event

    async_sink = AsyncSink()
    async_event = RuntimeEvent(type=RuntimeEventType.ERROR, error="failed")

    assert await emit_runtime_event(async_sink, async_event) is async_event
    assert async_sink.events == [async_event]


def test_legacy_observer_bridge_preserves_process_type_content_and_merge_key():
    message = json.dumps(
        {
            "type": "model_output_thinking",
            "content": "thinking chunk",
        },
        ensure_ascii=False,
    )

    event = runtime_event_from_legacy_observer_message(
        message,
        request_id="req-1",
        agent_name="root",
    )

    assert event.type == RuntimeEventType.LEGACY_PROCESS
    assert event.request_id == "req-1"
    assert event.agent_name == "root"
    assert event.compat_process_type == "model_output_thinking"
    assert event.content == "thinking chunk"
    assert event.payload == {
        "type": "model_output_thinking",
        "content": "thinking chunk",
    }
    assert event.unit_merge_key == "legacy:model_output_thinking"


def test_legacy_observer_bridge_handles_token_count_and_plain_text_diagnostics():
    token_event = runtime_event_from_legacy_observer_message(
        {
            "type": "token_count",
            "content": '{"prompt_tokens": 10}',
        },
        request_id="req-1",
    )
    text_event = runtime_event_from_legacy_observer_message("raw diagnostic")

    assert token_event.compat_process_type == "token_count"
    assert token_event.content == '{"prompt_tokens": 10}'
    assert token_event.unit_merge_key is None
    assert text_event.compat_process_type == "other"
    assert text_event.content == "raw diagnostic"


def test_runtime_event_to_process_payload_preserves_legacy_sse_shape_and_merge_key():
    event = runtime_event_from_legacy_observer_message(
        {"type": "model_output_code", "content": "Code: ```python"},
        request_id="req-1",
    )

    payload = runtime_event_to_process_payload(event)

    assert payload.process_type == "model_output_code"
    assert payload.content == "Code: ```python"
    assert payload.unit_merge_key == "legacy:model_output_code"
    assert payload.to_sse_payload() == {
        "type": "model_output_code",
        "content": "Code: ```python",
    }


def test_runtime_event_to_process_payload_maps_standard_final_error_and_token_events():
    final_payload = runtime_event_to_process_payload(
        RuntimeEvent(type=RuntimeEventType.FINAL_ANSWER, content="done")
    )
    error_payload = runtime_event_to_process_payload(
        RuntimeEvent(type=RuntimeEventType.ERROR, error="safe failure")
    )
    token_payload = runtime_event_to_process_payload(
        RuntimeEvent(
            type=RuntimeEventType.TOKEN_COUNT,
            token_usage={"prompt_tokens": 10, "completion_tokens": 2},
        )
    )

    assert final_payload.to_sse_payload() == {
        "type": "final_answer",
        "content": "done",
    }
    assert error_payload.to_sse_payload() == {
        "type": "error",
        "content": DEFAULT_SAFE_RUNTIME_ERROR_MESSAGE,
    }
    assert error_payload.metadata["raw_error"] == "safe failure"
    assert token_payload.process_type == "token_count"
    assert json.loads(token_payload.content) == {
        "prompt_tokens": 10,
        "completion_tokens": 2,
    }


def test_runtime_event_to_process_payload_maps_artifact_to_skill_files_payload():
    payload = runtime_event_to_process_payload(
        RuntimeEvent(
            type=RuntimeEventType.ARTIFACT_CREATED,
            artifact={"object_name": "skill/result.txt", "name": "result.txt"},
        )
    )

    assert payload.process_type == "skill_files"
    assert json.loads(payload.content) == {
        "skill_file_uploads": [
            {"object_name": "skill/result.txt", "name": "result.txt"}
        ]
    }


def test_standard_runtime_events_map_to_existing_process_types():
    events = [
        RuntimeEvent(type=RuntimeEventType.RUN, content={"status": "started"}),
        RuntimeEvent(type=RuntimeEventType.STEP, content={"step": 1}),
        RuntimeEvent(type=RuntimeEventType.MODEL_DELTA, delta="thinking"),
        RuntimeEvent(type=RuntimeEventType.MODEL_REASONING, reasoning="reason"),
        RuntimeEvent(type=RuntimeEventType.TOOL_CALL, tool_name="search", tool_input={"q": "x"}),
        RuntimeEvent(type=RuntimeEventType.TOOL_DISPLAY, content={"title": "card"}),
        RuntimeEvent(type=RuntimeEventType.RETRIEVAL, content=[{"title": "source"}]),
        RuntimeEvent(type=RuntimeEventType.IMAGE, content=["https://example.test/image.png"]),
        RuntimeEvent(type=RuntimeEventType.RUN_FINISHED, content={"status": "completed"}),
    ]

    payloads = [runtime_event_to_process_payload(event) for event in events]

    assert [payload.process_type for payload in payloads] == [
        "agent_new_run",
        "step_count",
        "model_output_thinking",
        "model_output_deep_thinking",
        "tool",
        "card",
        "search_content",
        "picture_web",
        "agent_finish",
    ]
    assert payloads[2].unit_merge_key == "runtime:model_output_thinking"
    assert payloads[3].unit_merge_key == "runtime:model_output_deep_thinking"


def test_runtime_event_delivery_items_cover_sse_persistence_monitoring_and_artifacts():
    events = [
        runtime_event_from_legacy_observer_message(
            {"type": "model_output_thinking", "content": "part 1"},
            request_id="req-1",
        ),
        runtime_event_from_legacy_observer_message(
            {"type": "model_output_thinking", "content": "part 2"},
            request_id="req-1",
        ),
        RuntimeEvent(
            type=RuntimeEventType.ARTIFACT_CREATED,
            request_id="req-1",
            sequence=2,
            artifact={
                "file_name": "result.txt",
                "object_name": "skill/result.txt",
                "file_size": 12,
                "url": "s3://bucket/skill/result.txt",
                "preview_url": "https://preview",
            },
            metadata={"operator": "skill_file_upload"},
        ),
    ]

    items = runtime_events_to_delivery_items(events, starting_unit_index=7)

    assert [item.sse_payload for item in items[:2]] == [
        {"type": "model_output_thinking", "content": "part 1"},
        {"type": "model_output_thinking", "content": "part 2"},
    ]
    assert [item.message_unit for item in items[:2]] == [
        {
            "type": "model_output_thinking",
            "content": "part 1",
            "unit_index": 7,
            "unit_merge_key": "legacy:model_output_thinking",
        },
        {
            "type": "model_output_thinking",
            "content": "part 2",
            "unit_index": 7,
            "unit_merge_key": "legacy:model_output_thinking",
        },
    ]
    assert items[2].sse_payload["type"] == "skill_files"
    assert json.loads(items[2].sse_payload["content"]) == {
        "skill_file_uploads": [
            {
                "file_name": "result.txt",
                "object_name": "skill/result.txt",
                "file_size": 12,
                "url": "s3://bucket/skill/result.txt",
                "preview_url": "https://preview",
            }
        ]
    }
    assert items[2].message_unit is None
    assert items[2].skill_file_attachments == [
        {
            "object_name": "skill/result.txt",
            "name": "result.txt",
            "type": "file",
            "size": 12,
            "url": "s3://bucket/skill/result.txt",
            "presigned_url": "https://preview",
            "description": "",
        }
    ]
    assert items[2].monitoring_metadata == {
        "runtime_event_type": "artifact_created",
        "runtime_event_sequence": 2,
        "runtime_request_id": "req-1",
        "operator": "skill_file_upload",
    }


def test_smolagents_process_type_coverage_matches_current_observer_enum():
    observer_path = (
        Path(__file__).resolve().parents[3]
        / "sdk"
        / "nexent"
        / "core"
        / "utils"
        / "observer.py"
    )
    source = observer_path.read_text(encoding="utf-8")
    process_types = set(re.findall(r'=\s*"([a-z_]+)"', source.split("class MessageObserver", 1)[0]))

    assert set(SMOLAGENTS_PROCESS_TYPE_COMPATIBILITY) == process_types
    assert set(SMOLAGENTS_PROCESS_TYPE_COMPATIBILITY.values()) == {"complete"}
