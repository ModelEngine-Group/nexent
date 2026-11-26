# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Completion-event unit regressions at the stream-to-persistence boundary."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.responses import StreamingResponse

from contracts.conversation import MessageSource
from management.services.agent import agentos_events, prepared_projection, prepared_turn
from .test_agentos_conversation_projection import REFERENCE, event, response


@pytest.fixture
def stream_capture(monkeypatch):
    persist = AsyncMock(return_value=42)
    monkeypatch.setattr(prepared_projection, "run_blocking", persist)

    turn = SimpleNamespace(reference=REFERENCE, user_id="user", tenant_id="tenant", message_index=3)

    async def capture(source_events, *, status="completed", final_answer_mode="delta", core="smolagents"):
        monkeypatch.setattr(agentos_events, "NEXENT_AGENT_CORE", core)
        frames = []
        published = []
        capture.published = published

        async def source():
            current_status = status
            for index, item in enumerate(source_events, 1):
                if isinstance(item, asyncio.CancelledError):
                    raise item
                if isinstance(item, Exception):
                    current_status = "failed"
                    break
                frame = event(index, "agentos_observer", json.dumps(item))
                frames.append(frame)
                yield frame
            terminal = event(len(frames) + 1, "agentos_terminal", json.dumps({"status": current_status}))
            frames.append(terminal)
            yield terminal

        async def project(_turn, _client):
            return await prepared_projection.resume_assistant_projection(
                AsyncMock(return_value=response(*frames)), REFERENCE, "user", "tenant",
                message_index=3, message_source=MessageSource.CHAT,
            )

        monkeypatch.setattr(prepared_turn, "_finish_projection", project)
        client = SimpleNamespace(resume=AsyncMock(return_value=StreamingResponse(source())))
        public = await prepared_turn._stream_turn(
            turn, client, include_journal_controls=False, complete_answer=final_answer_mode == "complete",
        )
        async for frame in agentos_events.iter_sse_frames(public):
            if frame.startswith(b"data: {"):
                published.append(json.loads(frame.removeprefix(b"data: ")))
        persist.assert_awaited_once()
        return published, persist.await_args.kwargs if persist.side_effect is None else None

    capture.persist = persist


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
