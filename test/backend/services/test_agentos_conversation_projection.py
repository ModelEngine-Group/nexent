# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify Management projection of retained AgentOS events."""

from unittest.mock import AsyncMock

import json

import httpx
import pytest
from starlette.responses import StreamingResponse

from contracts.agentos import AgentRunReference
from contracts.conversation import MessageSource
from contracts.errors.exceptions import RuntimeServiceUnavailableError
from management.services.agent import prepared_projection

REFERENCE = AgentRunReference(conversation_id=42, run_id="a" * 32)


def event(index, kind, value):
    return f"id: {REFERENCE.run_id}:{index}\nevent: {kind}\ndata: {value}\n\n".encode()


def response(*values):
    async def body():
        for value in values:
            if isinstance(value, Exception):
                raise value
            yield value
    return StreamingResponse(body())


@pytest.mark.asyncio
async def test_resumes_from_last_complete_frame_and_commits_one_projection(monkeypatch):
    first = event(1, "agentos_observer", '{"type":"final_answer","content":"hello "}')
    second = event(2, "agentos_observer", '{"type":"final_answer","content":"world"}')
    terminal = event(3, "agentos_terminal", '{"status":"completed"}')
    resume = AsyncMock(side_effect=[response(first[:9], first[9:], second[:8], httpx.ReadError("closed")),
                                    response(second, terminal)])

    async def save(_task, _function, *, lane, owner, **fields):
        assert fields["projection_run_id"] == REFERENCE.run_id
        assert (fields["user_id"], fields["tenant_id"], fields["conversation_id"]) == ("actor", "tenant", 42)
        assert fields["message_content"] == "hello world"
        assert len(fields["message_units"]) == 1
        assert fields["message_source"] is MessageSource.AUTOMATION
        return 91

    persist = AsyncMock(side_effect=save)
    monkeypatch.setattr(prepared_projection, "run_blocking", persist)
    result = await prepared_projection.resume_assistant_projection(
        resume, REFERENCE, "actor", "tenant", message_index=5, message_source=MessageSource.AUTOMATION,
    )
    assert (result.assistant_message_id, result.status, result.chunks) == (91, "completed", 2)
    assert [call.args[0].after_event_id for call in resume.await_args_list] == [None, f"{REFERENCE.run_id}:1"]
    persist.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("frames", [
    [event(2, "agentos_terminal", '{"status":"completed"}')],
    [event(1, "agentos_observer", '{"type":"skill_artifact","content":{"artifacts":[]}}')],
    [event(1, "agentos_observer",
           '{"type":"file_artifact","content":{"artifacts":[{"object_name":"workspace/other/'
           + REFERENCE.run_id + '/outputs/report.txt"}]}}')],

    [event(1, "agentos_observer", '{"type":"final_answer","content":"incomplete"}')],
])
async def test_unsafe_or_incomplete_stream_is_never_committed(monkeypatch, frames):
    resume = AsyncMock(side_effect=[response(*frames), response()])
    persist = AsyncMock()
    monkeypatch.setattr(prepared_projection, "run_blocking", persist)
    with pytest.raises(RuntimeServiceUnavailableError):
        await prepared_projection.resume_assistant_projection(
            resume, REFERENCE, "actor", "tenant", message_index=1, message_source=MessageSource.AUTOMATION,
        )
    persist.assert_not_called()


@pytest.mark.asyncio
async def test_persists_uploaded_artifact_with_stable_fields_only(monkeypatch):
    name = f"workspace/actor/{REFERENCE.run_id}/outputs/report.txt"
    artifact = dict(
        object_name=name, file_name="report.txt", file_size=9,
        url=f"s3://bucket/{name}", presigned_url="short-lived-url",
    )
    raw = json.dumps({"type": "file_artifact", "content": {"artifacts": [artifact]}})
    resume = AsyncMock(return_value=response(
        event(1, "agentos_observer", raw),
        event(2, "agentos_terminal", '{"status":"stopped"}'),
    ))
    persist = AsyncMock(return_value=91)
    monkeypatch.setattr(prepared_projection, "run_blocking", persist)
    result = await prepared_projection.resume_assistant_projection(
        resume, REFERENCE, "actor", "tenant", message_index=5, message_source=MessageSource.AUTOMATION,
    )
    assert result.status == "stopped"
    files = persist.await_args.kwargs["skill_files"]
    assert files == [dict(object_name=name, name="report.txt", type="file", size=9,
                          url=f"s3://bucket/{name}", description="")]


@pytest.mark.asyncio
async def test_history_checkpoint_is_included_in_the_terminal_transaction(monkeypatch):
    def checkpoint(status):
        content = json.dumps({
            "status": status, "persist_status": "not_configured",
            "summary": {"markdown": "earlier history"}, "covered_through_message_id": 16,
        })
        return json.dumps({"type": "history_summary", "content": content})

    resume = AsyncMock(return_value=response(
        event(1, "agentos_observer", checkpoint("compacting")),
        event(2, "agentos_observer", checkpoint("accepted")),
        event(3, "agentos_terminal", '{"status":"completed"}'),
    ))
    persist = AsyncMock(return_value=91)
    monkeypatch.setattr(prepared_projection, "run_blocking", persist)
    await prepared_projection.resume_assistant_projection(
        resume, REFERENCE, "actor", "tenant", message_index=5, message_source=MessageSource.AUTOMATION,
    )
    batch = persist.await_args.kwargs
    assert batch["message_units"] == []
    assert batch["history_checkpoints"] == [{
        "summary": {"markdown": "earlier history"}, "covered_through_message_id": 16,
    }]
