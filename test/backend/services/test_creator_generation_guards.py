# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Generation fences for creator leases, late writes and cancellation."""

import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import fakeredis
import pytest

from contracts.errors.exceptions import (
    RuntimeCapacityExceededError,
    RuntimeQueueTimeoutError,
)
from infrastructure.redis.run_state import RuntimeStateService
from management.services.conversation import creator_runtime
from management.services.conversation.creator_runtime import CreatorControl
from nexent.core.concurrency.errors import ThreadCapacityExceeded, ThreadQueueTimedOut
from runtime.agentos import ephemeral


def test_creator_redis_claim_lease_and_stale_generation_fences(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.redis.run_state.RUNTIME_STATE_REDIS_URL",
        "redis://controlled-fixture",
    )
    state = RuntimeStateService()
    state._client = fakeredis.FakeRedis(decode_responses=True)
    assert state.claim_creator_run("user", 91, "old")
    assert not state.claim_creator_run("user", 91, "concurrent")
    assert state.creator_lease("user", 91, "old", renew=True)
    assert state.append_stream_event("user", 91, "old-event", generation="old")
    # Expiry represents the old runtime process losing ownership.
    state.client.delete(state._run_key("user", 91) + ":creator-lease")
    assert state.claim_creator_run("user", 91, "new")
    assert not state.creator_lease("user", 91, "old", renew=True)
    assert state.append_stream_event("user", 91, "late-event", generation="old") is None
    state.mark_stream_completed("user", 91, "failed", generation="old")
    state.mark_run_finished("user", 91, "stopped", generation="old")
    assert not state.set_cancel_signal("user", 91, expected_generation="old")
    assert not state.cancel_creator_run("user", 91, expected_generation="old")
    assert state.cancel_creator_run("user", 91, expected_generation="new")
    assert state.is_cancelled("user", 91)
    assert state.get_run_state("user", 91)["generation"] == "new"
    assert state.get_run_state("user", 91)["status"] == "running"
    assert state.get_stream_status("user", 91) == {}
    assert state.read_stream_events("user", 91) == []
    assert state.append_stream_event("user", 91, "new-event", generation="new")
    state.mark_stream_completed("user", 91, "completed", generation="new")
    state.mark_run_finished("user", 91, "completed", generation="new")
    assert state.get_stream_status("user", 91)["status"] == "completed"
    assert state.get_run_state("user", 91)["status"] == "completed"
    assert not state.cancel_creator_run("user", 91, expected_generation="new")


@pytest.mark.asyncio
async def test_local_creator_stop_keeps_the_current_generation(monkeypatch):
    manager = Mock()
    monkeypatch.setattr(creator_runtime, "agent_run_manager", manager)
    current = CreatorControl().registered_info()
    manager.get_agent_run_info.return_value = current
    generation = current._automation_runtime_generation
    assert await creator_runtime.stop_creator(21, "user", "obsolete") is False
    manager.stop_local_run.assert_not_called()
    assert await creator_runtime.stop_creator(21, "user", generation) is manager.stop_local_run.return_value
    manager.stop_local_run.assert_called_once_with(21, "user", expected_run=current)


@pytest.mark.asyncio
async def test_skill_creator_binds_the_admitted_worker_without_signalling_stop(monkeypatch):
    info = SimpleNamespace(stop_event=Event())
    execution = MagicMock()
    deferred = object()
    calls = []

    async def agent_run(run_info, **kwargs):
        calls.append((run_info, kwargs))
        yield json.dumps({"type": "final_answer", "content": "plain output"})

    monkeypatch.setattr(ephemeral, "agent_run", agent_run)
    events = [event async for event in ephemeral._observer_stream(
        info, execution, deferred, creator_mode="nl2skill",
    )]
    assert calls[0][0] is info
    assert calls[0][1]["execution"] is execution
    assert calls[0][1]["deferred_run"] is deferred
    assert events[-1] == "event: agentos_execution_complete\ndata: {}\n\n"
    assert not info.stop_event.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [False, True])
async def test_creator_admission_reports_overload_and_cancels_queued_worker(
    monkeypatch, queued
):
    manager = MagicMock()
    monkeypatch.setattr(creator_runtime, "runtime_thread_manager", manager)
    control = CreatorControl()
    control.configure(SimpleNamespace())
    if queued:
        manager.wait_until_started = AsyncMock(
            side_effect=ThreadQueueTimedOut("agent-run", 1)
        )
    else:
        manager.submit.side_effect = ThreadCapacityExceeded("agent-run", 1, 1)
    with pytest.raises(
        RuntimeQueueTimeoutError if queued else RuntimeCapacityExceededError
    ):
        await control.admit()
    if queued:
        assert control.stop_event.is_set()
        manager.cancel.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("requested,expected", [("retired", False), ("current", True)])
async def test_remote_creator_stop_is_fenced_by_the_request_generation(monkeypatch, requested, expected):
    state = SimpleNamespace(
        enabled=True,
        get_run_state_async=AsyncMock(return_value={"status": "running", "generation": "current"}),
        creator_lease_async=AsyncMock(return_value=True),
        _run_managed=AsyncMock(return_value=True),
        set_cancel_signal=MagicMock(),
    )
    monkeypatch.setattr(creator_runtime, "runtime_state_service", state)
    monkeypatch.setattr(creator_runtime, "agent_run_manager", SimpleNamespace(get_agent_run_info=lambda *_: None))

    result = await creator_runtime.stop_creator(91, "owner", requested)

    assert result is expected
    state.get_run_state_async.assert_awaited_once_with("owner", 91)
    if expected:
        state._run_managed.assert_awaited_once_with(
            "creator-stop", state.set_cancel_signal, "owner", 91, "current",
        )
    else:
        state._run_managed.assert_not_awaited()
