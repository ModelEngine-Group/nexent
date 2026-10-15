"""Completion-event unit regressions at the stream-to-persistence boundary."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Reuse the existing service suite's isolated dependency setup. Product stream
# processing and final-answer projection remain real in these unit tests.
from . import test_agent_service as service_tests


@pytest.fixture
def stream_capture(monkeypatch):
    service = service_tests.agent_execution
    batches = []
    monkeypatch.setattr(service, "save_message", MagicMock(return_value=42))
    monkeypatch.setattr(service, "persist_assistant_run_batch", lambda **kwargs: batches.append(kwargs))
    monkeypatch.setattr(service, "_unregister_agent_run_after_execution", MagicMock())
    monkeypatch.setattr(service.streaming_channel_manager, "complete_channel", AsyncMock())
    monkeypatch.setattr(service, "_cleanup_channel_later", AsyncMock())

    async def capture(source_events):
        async def source(*_args, **_kwargs):
            for event in source_events:
                yield json.dumps(event)

        monkeypatch.setattr(service, "agent_run", source)
        info = SimpleNamespace(
            agent_config=SimpleNamespace(pre_run_tool_events=()), cancellation_scope=None,
            stop_event=asyncio.Event(), human_interaction=None,
            attempt_outcome="completed", thread_future=None,
        )
        channel = SimpleNamespace(publish=AsyncMock())
        request = service_tests.AgentRequest(
            agent_id=1, conversation_id=999, query="test", history=[], minio_files=[], is_debug=False)
        raw = [chunk async for chunk in service._stream_agent_chunks(
            request, "user", "tenant", info, MagicMock(), channel=channel)]
        published = [json.loads(chunk.removeprefix("data: ").strip())
                     for chunk in raw if chunk.startswith("data: {" )]
        assert channel.publish.await_count == len(raw)
        assert len(batches) == 1
        return published, batches[0]

    return capture


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", ["", "Verified answer"])
async def test_completion_is_forwarded_once_and_persistence_has_only_the_canonical_body(stream_capture, verified):
    source = [
        {"type": "step_count", "content": "Step 1", "step_id": "step"},
        {"type": "final_answer", "content": "Draft ", "step_id": "step", "answer_phase": "delta"},
        {"type": "final_answer", "content": "answer", "step_id": "step", "answer_phase": "delta"},
        {"type": "final_answer", "content": verified, "step_id": "step", "answer_phase": "complete"},
    ]
    published, batch = await stream_capture(source)
    completions = [event for event in published if event.get("answer_phase") == "complete"]
    assert len(completions) == 1 and completions[0]["content"] == verified
    units = batch["message_units"]
    assert [(item["type"], item["content"]) for item in units] == [("final_answer", verified or "Draft answer")]
    assert batch["message_content"] == (verified or "Draft answer")
    assert all("_step_id" not in item for item in units)


@pytest.mark.asyncio
async def test_child_empty_completion_does_not_replace_or_repeat_parent_result(stream_capture):
    source = []
    for invocation, answer in (("child", "Child"), (None, "Parent")):
        source.extend([
            {"type": "step_count", "content": "Step 1", "step_id": "same", "invocation_id": invocation},
            {"type": "final_answer", "content": answer, "step_id": "same", "invocation_id": invocation,
             "answer_phase": "delta"},
            {"type": "final_answer", "content": "", "step_id": "same", "invocation_id": invocation,
             "answer_phase": "complete"},
        ])
    published, batch = await stream_capture(source)
    assert len([item for item in published if item.get("answer_phase") == "complete"]) == 2
    assert [(item.get("invocation_id"), item["content"]) for item in batch["message_units"]] == [
        ("child", "Child"), (None, "Parent")]
    assert batch["message_content"] == "Parent"
