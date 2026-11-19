# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Background results come from the scoped execution's terminal projection."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from contracts.conversation import MessageSource
from contracts.errors.exceptions import RuntimeServiceUnavailableError
from management.services.agent import background, prepared_projection
from management.services.automation import runner
from .test_agentos_conversation_projection import REFERENCE, event, response


@pytest.fixture
def projection(mocker):
    record = {
        "projection_message_index": 5, "runtime_run_id": REFERENCE.run_id,
        "user_id": "owner", "tenant_id": "tenant", "user_message_id": 101,
    }
    mocker.patch.object(runner, "get_prepared_projection_receipt", return_value=None)
    persist = mocker.patch.object(prepared_projection, "persist_prepared_assistant_projection", return_value=123)
    return record, persist


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "failed", "stopped", None])
@pytest.mark.parametrize("persisted", [False, True])
async def test_background_requires_completed_and_persisted_terminal_projection(projection, status, persisted):
    record, persist = projection
    first = event(1, "agentos_observer", '{"type":"final_answer","content":"Current answer"}')
    frames = [first]
    if status is not None:
        frames.append(event(2, "agentos_terminal", json.dumps({"status": status})))
    if not persisted:
        persist.side_effect = RuntimeError("controlled storage failure")

    async def acknowledge(*_args):
        persist.assert_called_once()

    transport = SimpleNamespace(
        resume=AsyncMock(side_effect=[response(*frames), response()]),
        acknowledge_projection=AsyncMock(side_effect=acknowledge),
    )

    if status is None:
        with pytest.raises(RuntimeServiceUnavailableError):
            await background._project(transport, REFERENCE, record)
        persist.assert_not_called()
        transport.acknowledge_projection.assert_not_awaited()
        return
    if not persisted:
        with pytest.raises(RuntimeError, match="controlled storage failure"):
            await background._project(transport, REFERENCE, record)
    elif status == "completed":
        result = await background._project(transport, REFERENCE, record)
        assert result.run_id == REFERENCE.run_id
        assert (result.assistant_message_id, result.chunks) == (123, 1)
    else:
        with pytest.raises(HTTPException) as error:
            await background._project(transport, REFERENCE, record)
        assert error.value.detail == {"code": "AGENTOS_BACKGROUND_NOT_COMPLETED"}
    persist.assert_called_once()
    if persisted:
        transport.acknowledge_projection.assert_awaited_once_with(REFERENCE, "owner", "tenant")
    else:
        transport.acknowledge_projection.assert_not_awaited()
    fields = persist.call_args.kwargs
    assert fields["projection_run_id"] == REFERENCE.run_id
    assert fields["message_source"] is MessageSource.AUTOMATION
    assert fields["message_content"] == "Current answer"
    assert fields["terminal_status"] == status


@pytest.mark.asyncio
async def test_background_cancellation_closes_journal_without_committing(projection):
    record, persist = projection
    started = asyncio.Event()
    closed = asyncio.Event()

    async def journal():
        try:
            started.set()
            yield event(1, "agentos_observer", '{"type":"final_answer","content":"Uncommitted"}')
            await asyncio.Future()
        finally:
            closed.set()

    from starlette.responses import StreamingResponse

    transport = SimpleNamespace(
        resume=AsyncMock(return_value=StreamingResponse(journal())), acknowledge_projection=AsyncMock(),
    )
    task = asyncio.create_task(background._project(transport, REFERENCE, record))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert closed.is_set()
    persist.assert_not_called()
    transport.acknowledge_projection.assert_not_awaited()
