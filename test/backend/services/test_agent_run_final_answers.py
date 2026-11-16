# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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

    async def capture(source_events, *, outcome="completed", stopped=False, **stream_kwargs):
        async def source(*_args, **_kwargs):
            for event in source_events:
                if isinstance(event, BaseException):
                    raise event
                yield json.dumps(event)

        monkeypatch.setattr(service, "agent_run", source)
        info = SimpleNamespace(
            observer=SimpleNamespace(),
            agent_config=SimpleNamespace(pre_run_tool_events=()), cancellation_scope=None,
            stop_event=asyncio.Event(), human_interaction=None,
            attempt_outcome=outcome, thread_future=None,
        )
        if stopped:
            info.stop_event.set()
        channel = SimpleNamespace(publish=AsyncMock())
        capture.channel = channel
        request = service_tests.AgentRequest(
            agent_id=1, conversation_id=999, query="test", history=[], minio_files=[], is_debug=False)
        raw = [chunk async for chunk in service._stream_agent_chunks(
            request, "user", "tenant", info, None, channel=channel, **stream_kwargs)]
        published = [json.loads(chunk.removeprefix("data: ").strip())
                     for chunk in raw if chunk.startswith("data: {" )]
        assert channel.publish.await_count == len(raw)
        assert len(batches) <= 1
        return published, batches[0] if batches else None

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


@pytest.mark.asyncio
async def test_search_hit_snapshots_survive_stream_buffering_without_filename_grouping(stream_capture):
    metadata = [{"count": 0, "enabled": False, "tags": [0, False]}, {"standards": {"code": {"level": "E"}}}]
    hits = [
        {"title": "same.pdf", "filename": "same.pdf", "text": f"chunk {index}", "url": "",
         "source_type": "file", "search_type": "aidp_search", "tool_sign": "j", "cite_index": index + 1,
         "score_details": {"metadata": value, "chunk_id": f"chunk-{index}", "retrieval_source": "vector"}}
        for index, value in enumerate(metadata)
    ]
    published, batch = await stream_capture([
        {"type": "search_content", "content": json.dumps(hits), "tool_call_id": "call-search", "invocation_id": "child"},
        {"type": "final_answer", "content": "Answer [[j1]][[j2]]"},
    ])
    assert json.loads(published[0]["content"]) == hits
    records = batch["search_records"]
    assert len(records) == 2
    assert [record["aidp_metadata"] for record in records] == metadata
    assert [record["aidp_source_reference"]["chunk_id"] for record in records] == ["chunk-0", "chunk-1"]
    assert all("metadata" not in record["aidp_source_reference"] for record in records)
    unit = batch["message_units"][0]
    assert unit["tool_call_id"] == "call-search" and unit["invocation_id"] == "child"
    assert all(record["unit_index"] == unit["unit_index"] for record in records)
