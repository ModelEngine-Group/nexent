# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the durable tracking path that replaced legacy Runtime channels."""

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb import agent_execution
from runtime.agentos import prepared_run


ACTOR = ServicePrincipal("owner", "tenant")
RUN_ID = "a" * 32
IDENTITY = agent_execution.RunIdentity("tenant", "owner", 42, RUN_ID)


@pytest.mark.asyncio
async def test_prepared_admission_tracks_the_same_identity_as_its_journal(mocker):
    async def inline(_task, function, *args):
        return function(*args)

    mocker.patch.object(prepared_run, "_control_io", side_effect=inline)
    ledger = mocker.patch.object(prepared_run, "begin_execution")
    track = mocker.patch.object(prepared_run, "track_execution")
    journal = mocker.patch.object(prepared_run, "RunJournal")
    producer = mocker.patch.object(prepared_run, "_produce", new_callable=AsyncMock)
    tasks = set()
    mocker.patch.object(prepared_run, "agent_stream_producer_tasks", tasks)
    payload = SimpleNamespace(conversation_id=42, run_id=RUN_ID)

    result = await prepared_run._admit(payload, ACTOR)
    await asyncio.gather(*tasks)

    assert result.conversation_id == 42 and result.run_id == RUN_ID
    ledger.assert_called_once_with(IDENTITY)
    track.assert_called_once_with(IDENTITY)
    journal.assert_called_once_with("tenant", "owner", 42, RUN_ID)
    journal.return_value.start.assert_called_once_with()
    producer.assert_awaited_once_with(payload, ACTOR, IDENTITY, journal.return_value)
    assert not tasks


@pytest.mark.parametrize("ledger_failure", [False, True])
def test_finishing_releases_live_registration_even_when_ledger_write_fails(mocker, ledger_failure):
    session = Mock()
    session.execute.return_value.rowcount = 1
    mocker.patch.object(agent_execution, "get_db_session", return_value=nullcontext(session))
    untrack = mocker.patch.object(agent_execution, "untrack_execution")
    if ledger_failure:
        session.execute.side_effect = SQLAlchemyError("database unavailable")
        with pytest.raises(SQLAlchemyError, match="database unavailable"):
            agent_execution.finish_execution(IDENTITY, "failed")
    else:
        assert agent_execution.finish_execution(IDENTITY, "failed")
    untrack.assert_called_once_with(IDENTITY)


@pytest.mark.asyncio
async def test_journal_start_failure_finishes_the_tracking_record_without_starting_a_producer(mocker):
    async def inline(_task, function, *args):
        return function(*args)

    mocker.patch.object(prepared_run, "_control_io", side_effect=inline)
    mocker.patch.object(prepared_run, "begin_execution")
    mocker.patch.object(prepared_run, "track_execution")
    journal = mocker.patch.object(prepared_run, "RunJournal")
    journal.return_value.start.side_effect = RuntimeError("journal unavailable")
    finish = mocker.patch.object(prepared_run, "finish_execution")
    produce = mocker.patch.object(prepared_run, "_produce")
    payload = SimpleNamespace(conversation_id=42, run_id=RUN_ID)

    with pytest.raises(HTTPException) as failure:
        await prepared_run._admit(payload, ACTOR)

    assert failure.value.status_code == 503
    finish.assert_called_once_with(IDENTITY, "failed")
    produce.assert_not_called()
