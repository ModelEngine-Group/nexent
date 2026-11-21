# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Publish only owned, stable artifact metadata across the public stream boundary."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.responses import StreamingResponse

from contracts.agentos import AgentResume
from management.services.agent import agentos_events as events

RUN_ID = "a" * 32
OWN = f"workspace/actor/{RUN_ID}/outputs/report.txt"
FOREIGN = f"workspace/another-user/{RUN_ID}/outputs/hidden.txt"


@pytest.fixture
def signer(mocker):
    async def sign(_label, callback, artifacts, *, lane, owner):
        assert callback is events.enrich_file_uploads_with_presigned_urls
        assert (lane, owner) == ("control-io", "management")
        return [{**item, "download_url": "https://example.test/download"} for item in artifacts]

    return mocker.patch.object(events, "run_blocking", side_effect=sign)


def frame(kind, content):
    return b"data: " + json.dumps({"type": kind, "content": content}).encode()


async def test_public_artifact_frame_normalizes_names_and_discards_foreign_items(signer):
    items = [None, {"object_name": FOREIGN}, {"object_name": OWN, "file_name": "folder/report.txt",
             "size": 42, "mime_type": "text/plain", "presigned_url": "expired"}]
    data, failed = await events._present_observer(
        frame("file_artifact", json.dumps({"artifacts": items})), SimpleNamespace(run_id=RUN_ID), "actor",
    )
    assert failed is False
    payload = json.loads(data.removeprefix(b"data: "))
    assert payload["type"] == "files"
    assert json.loads(payload["content"]) == {"file_uploads": [{
        "object_name": OWN, "file_name": "report.txt", "file_size": 42, "mime_type": "text/plain",
        "status": "success", "download_url": "https://example.test/download",
    }]}
    signer.assert_awaited_once()


@pytest.mark.parametrize("data,error", [
    (b": keepalive", "Missing AgentOS observer data"),
    (b"data: []", "Unsupported AgentOS observer data"),
    (frame("skill_artifact", {}), "Unsupported AgentOS observer data"),
    (frame("file_artifact", {}), "Missing AgentOS output artifacts"),
])
async def test_public_observer_rejects_invalid_or_internal_frames(data, error, signer):
    with pytest.raises(ValueError, match=error):
        await events._present_observer(data, SimpleNamespace(run_id=RUN_ID), "actor")
    signer.assert_not_awaited()


async def test_ephemeral_publication_deduplicates_outputs_and_waits_for_end(signer):
    first = frame("file_artifact", {"artifacts": [{"object_name": OWN, "file_name": "old.txt", "size": -1}]})
    last = frame("file_artifact", {"artifacts": [{"object_name": OWN, "file_name": "latest.txt", "size": 11}]})
    text = frame("text", "answer")

    async def upstream():
        for item in (b": keepalive", b"data: not-json", first, frame("execution_result", {}), text, last):
            yield item + b"\n\n"

    response = events.present_ephemeral_stream(
        StreamingResponse(upstream(), headers={"content-length": "999"}), "actor", RUN_ID,
        opening_events=[{"type": "prepared", "content": "ready"}],
    )
    chunks = [chunk async for chunk in response.body_iterator]
    assert len(chunks) == 3
    assert json.loads(chunks[0].removeprefix(b"data: ")) == {"type": "prepared", "content": "ready"}
    assert chunks[1] == text + b"\n\n"
    published = json.loads(chunks[2].removeprefix(b"data: "))
    assert json.loads(published["content"])["file_uploads"] == [{
        "object_name": OWN, "file_name": "latest.txt", "file_size": 11, "status": "success",
        "download_url": "https://example.test/download",
    }]
    assert "content-length" not in response.headers
    signer.assert_awaited_once()


@pytest.mark.parametrize("terminal,expected", [
    (b'data: {"status":"completed"}', "completed"),
    (b'data: {"status":"running"}', "failed"),
    (b"data: not-json", "failed"),
])
async def test_legacy_stream_filters_private_units_and_rejects_invalid_terminal(terminal, expected):
    async def upstream():
        yield b": keep-alive\n\n"
        yield f"id: {RUN_ID}:1\nevent: agentos_execution_fact\ndata: {{\"content\":\"private\"}}\n\n".encode()
        yield f"id: {RUN_ID}:2\nevent: agentos_terminal\n".encode() + terminal + b"\n\n"

    projected = events.present_legacy_journal(StreamingResponse(upstream()), RUN_ID, 3, 2)
    data = b"".join([part async for part in projected.body_iterator])
    assert b": keep-alive" in data
    assert b"private" not in data and b"agentos_execution_fact" not in data
    terminal_frame = data.split(b"\n\n")[-2]
    event, _, body = terminal_frame.partition(b"\n")
    assert event == b"event: stream_status"
    assert json.loads(body.removeprefix(b"data: ")) == {"status": expected, "last_unit_index": 3}
    assert projected.headers["X-Last-Unit-Index"] == "4"


@pytest.mark.parametrize("case", ["wrong-run", "invalid-data", "no-projection", "upstream-error"])
async def test_public_resume_rejects_invalid_cursor_or_reports_a_safe_error(case, mocker):
    mocker.patch.object(events, "NEXENT_AGENT_CORE", "smolagents")
    confirm = AsyncMock(return_value=False)
    async def upstream():
        if case == "wrong-run":
            yield f'id: {"b" * 32}:1\nevent: agentos_observer\ndata: {{"type":"text","content":"wrong"}}\n\n'.encode()
        elif case == "invalid-data":
            yield f"id: {RUN_ID}:1\nevent: agentos_observer\ndata: not-json\n\n".encode()
        elif case == "no-projection":
            yield f'id: {RUN_ID}:1\nevent: agentos_terminal\ndata: {{"status":"completed"}}\n\n'.encode()
        else:
            yield b'event: agentos_error\ndata: {"code":"AGENTOS_CURSOR_UNAVAILABLE"}\n\n'

    response = events.present_public_resume(
        StreamingResponse(upstream()), AgentResume(conversation_id=42, run_id=RUN_ID), "actor",
        include_journal_controls=False, complete_answer=True, on_terminal=confirm,
    )
    chunks = [chunk async for chunk in response.body_iterator]
    if case == "wrong-run":
        assert chunks == []
    else:
        assert len(chunks) == 1
        error = json.loads(chunks[0].removeprefix(b"data: "))
        assert error["type"] == "error"
        assert "not-json" not in error["content"] and "AGENTOS_CURSOR_UNAVAILABLE" not in error["content"]
    assert confirm.await_count == (case == "no-projection")
