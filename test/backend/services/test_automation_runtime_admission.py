# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Background admission and cancellation ownership boundaries."""

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.agent import AgentRequest
from management.services.agent import lifecycle, run
from management.services.agent.background import BackgroundExecutionState
from runtime.executions import LocalExecutionRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["reset", "canceled", "context", "stream", "none"])
async def test_background_admission_resets_once_and_always_releases(monkeypatch, failure):
    events = []
    monkeypatch.setattr(run.agent_run_manager, "reserve_agent_run", Mock(return_value="reservation"))
    release = Mock()
    monkeypatch.setattr(run.agent_run_manager, "release_agent_run_reservation", release)

    async def reset(*args, **kwargs):
        events.append(("reset", kwargs["generation"]))
        if failure == "reset":
            raise RuntimeError("reset failed")

    def context(*args, **kwargs):
        events.append("context")
        if failure == "context":
            raise RuntimeError("context failed")
        return SimpleNamespace(metadata={}, enable_memory=False)

    async def stream(*args, execution_state, reservation_token, **kwargs):
        assert reservation_token == "reservation"
        events.append("stream")
        if failure == "stream":
            raise RuntimeError("stream failed")
        execution_state.assistant_message_id = 7
        execution_state.outcome = "completed"
        execution_state.persisted = True
        yield "done"

    monkeypatch.setattr(run.runtime_state_service, "reset_stream_async", reset)
    monkeypatch.setattr(run, "build_agent_run_context", context)
    monkeypatch.setattr(run, "agent_monitoring_context", lambda *a: nullcontext())
    monkeypatch.setattr(run, "generate_stream", stream)
    state = BackgroundExecutionState(runtime_generation="77", is_active=lambda: failure != "canceled")
    call = run.run_agent_background(AgentRequest(query="fixture", agent_id=1, conversation_id=9),
                                    "owner", "tenant", skip_user_save=True, execution_state=state)
    if failure == "none":
        assert (await call)["status"] == "completed"
    else:
        with pytest.raises(asyncio.CancelledError if failure == "canceled" else RuntimeError):
            await call
    assert events[0] == ("reset", "77") and events.count(("reset", "77")) == 1
    if failure == "canceled":
        assert events == [("reset", "77")]
    release.assert_called_once_with(9, "owner", "reservation")


def test_admission_rejection_does_not_reset_current_turn(monkeypatch):
    reset = AsyncMock()
    monkeypatch.setattr(run.runtime_state_service, "reset_stream_async", reset)
    monkeypatch.setattr(run.agent_run_manager, "reserve_agent_run", Mock(side_effect=RuntimeError("busy")))
    with pytest.raises(RuntimeError, match="busy"):
        asyncio.run(run.run_agent_background(AgentRequest(query="x", agent_id=1, conversation_id=9), "owner", "tenant"))
    reset.assert_not_awaited()


@pytest.mark.parametrize("matches", [False, True])
def test_generation_stop_only_targets_the_matching_local_run(monkeypatch, matches):
    info = SimpleNamespace(_automation_runtime_generation="77" if matches else "88")
    manager = lifecycle.agent_run_manager
    monkeypatch.setattr(manager, "get_agent_run_info", lambda *a: info)
    signal = Mock(return_value=matches)
    monkeypatch.setattr(lifecycle.runtime_state_service, "set_cancel_signal", signal)
    stop = Mock(return_value=True)
    monkeypatch.setattr(LocalExecutionRegistry, "stop_agent_run", stop)
    assert manager.stop_agent_run(9, "owner", expected_generation="77") is matches
    if matches:
        stop.assert_called_once_with(9, "owner", expected_run_info=info)
    else:
        stop.assert_not_called()


def test_identity_guard_cannot_stop_a_replacement_run(monkeypatch):
    registry = LocalExecutionRegistry()
    newer = SimpleNamespace(stop_event=Mock())
    monkeypatch.setattr(registry, "get_agent_run_info", lambda *a: newer)
    assert not registry.stop_agent_run(9, "owner", expected_run_info=object())
    newer.stop_event.set.assert_not_called()
