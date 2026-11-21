# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Reconcile staged public turns without projecting an unowned or expired execution."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from contracts.agentos import AgentRunReference, AgentRunState, AgentStop
from contracts.errors.exceptions import RuntimeServiceUnavailableError, RuntimeUpstreamError
from infrastructure.rdb.agent_admission import AdmissionScopeError
from management.services.agent import prepared_turn as service
from management.services.agent import runtime_client
from management.services.memory import prepared_completion

REFERENCE = AgentRunReference(conversation_id=42, run_id="a" * 32)


@pytest.fixture
def flow(mocker):
    async def inline(_label, callback, *args, **kwargs):
        return callback(*args, **kwargs)

    mocker.patch.object(service, "_io", side_effect=inline)
    turn = service.store.PreparedTurn(
        reference=REFERENCE, user_id="actor", tenant_id="tenant", message_index=1, assistant_message_id=None,
        staged_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    confirmed = replace(turn, assistant_message_id=61)
    return SimpleNamespace(
        turn=turn, confirmed=confirmed,
        close=mocker.patch.object(service.store, "close_turn"),
        confirm=mocker.patch.object(service.store, "confirm_turn", return_value=confirmed),
        project=mocker.patch.object(service, "_finish_projection"),
        client=SimpleNamespace(inspect_run=AsyncMock(), stop_run=AsyncMock()),
    )


def state(status, **changes):
    return AgentRunState.model_validate({
        **REFERENCE.model_dump(), "status": status, "latest_event_id": None,
        "cancellation_requested": False, **changes,
    })


@pytest.mark.parametrize("old,stop_status", [(False, None), (True, 404), (True, 503)])
async def test_missing_runtime_record_can_only_close_after_grace_period(flow, old, stop_status):
    turn = flow.turn if old else replace(flow.turn, staged_at=datetime.now(timezone.utc))
    flow.client.inspect_run.side_effect = RuntimeUpstreamError(404, b"", {})
    if stop_status:
        flow.client.stop_run.side_effect = RuntimeUpstreamError(stop_status, b"", {})

    if stop_status == 503:
        with pytest.raises(RuntimeUpstreamError, match="HTTP 503"):
            await service.reconcile_turn(turn, flow.client)
    else:
        await service.reconcile_turn(turn, flow.client)

    if old:
        flow.client.stop_run.assert_awaited_once_with(
            AgentStop(**REFERENCE.model_dump(), prevent_start=True), "actor", "tenant",
        )
    else:
        flow.client.stop_run.assert_not_awaited()
    if stop_status == 404:
        flow.close.assert_called_once_with(turn, failure_status="failed")
    else:
        flow.close.assert_not_called()
    flow.confirm.assert_not_called()
    flow.project.assert_not_awaited()


@pytest.mark.parametrize("outcome", ["starting", "foreign", "missing", "revoked", "conflict", "running"])
async def test_recovery_confirms_only_observed_owned_runtime(flow, outcome):
    inspected = state("starting" if outcome == "starting" else "running")
    if outcome == "foreign":
        inspected = state("running", conversation_id=43)
    elif outcome == "missing":
        flow.confirm.return_value = None
    elif outcome == "revoked":
        flow.confirm.side_effect = AdmissionScopeError
    elif outcome == "conflict":
        flow.confirm.side_effect = service.store.PreparedTurnConflict
    flow.client.inspect_run.return_value = inspected

    if outcome == "foreign":
        with pytest.raises(RuntimeServiceUnavailableError, match="different conversation run"):
            await service.reconcile_turn(flow.turn, flow.client)
    else:
        await service.reconcile_turn(flow.turn, flow.client)

    if outcome in {"starting", "foreign"}:
        flow.confirm.assert_not_called()
    else:
        flow.confirm.assert_called_once_with(flow.turn)
    if outcome == "revoked":
        flow.close.assert_called_once_with(flow.turn, failure_status="failed")
    elif outcome == "conflict":
        flow.close.assert_called_once_with(flow.turn)
        flow.client.stop_run.assert_awaited_once()
    else:
        flow.close.assert_not_called()
    flow.project.assert_not_awaited()


@pytest.mark.parametrize("status,http_status,expected", [
    ("completed", 404, "failed"), ("stopped", 410, "stopped"), ("completed", 503, None),
])
async def test_expired_journal_closes_the_reserved_turn_without_retrying_projection(flow, status, http_status, expected):
    flow.client.inspect_run.return_value = state(status)
    error = RuntimeUpstreamError(http_status, b"", {})
    flow.project.side_effect = error
    if expected is None:
        with pytest.raises(RuntimeUpstreamError) as exc:
            await service.reconcile_turn(flow.confirmed, flow.client)
        assert exc.value is error
        flow.close.assert_not_called()
    else:
        await service.reconcile_turn(flow.confirmed, flow.client)
        flow.close.assert_called_once_with(flow.confirmed, failure_status=expected)
    flow.project.assert_awaited_once_with(flow.confirmed, flow.client)


async def test_recovery_sweep_advances_after_a_failed_turn_and_retries_a_failed_page(flow, mocker):
    list_pending = mocker.patch.object(service.store, "pending_turns", side_effect=[
        [flow.turn], RuntimeError("database unavailable"), [],
    ])
    recover = mocker.patch.object(service, "reconcile_turn", side_effect=RuntimeError("journal deferred"))
    mocker.patch.object(runtime_client, "_agentos_client", return_value=flow.client)
    pause = AsyncMock(side_effect=[None, None, asyncio.CancelledError()])
    mocker.patch.object(service, "asyncio", SimpleNamespace(wait_for=asyncio.wait_for, gather=asyncio.gather, sleep=pause))
    with pytest.raises(asyncio.CancelledError):
        await service._recover_pending_turns()
    assert [call.args for call in list_pending.call_args_list] == [("", 4), (REFERENCE.run_id, 4), (REFERENCE.run_id, 4)]
    assert [call.args for call in pause.await_args_list] == [(1,), (1,), (3,)]
    recover.assert_awaited_once_with(flow.turn, flow.client)


async def test_prepared_turn_lifespan_discards_both_background_workers(mocker):
    started = {name: asyncio.Event() for name in ("turn", "memory")}
    stopped = []

    async def worker(name):
        started[name].set()
        try:
            await asyncio.Future()
        finally:
            stopped.append(name)

    mocker.patch.object(service, "_recover_pending_turns", side_effect=lambda: worker("turn"), new_callable=mocker.Mock)
    mocker.patch.object(
        prepared_completion, "recover_memory_jobs", side_effect=lambda: worker("memory"), new_callable=mocker.Mock,
    )
    async with service.prepared_turn_lifespan():
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), timeout=5)
        assert stopped == []
    assert set(stopped) == {"turn", "memory"}
