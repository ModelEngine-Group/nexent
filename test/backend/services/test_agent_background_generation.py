# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Background preparation and memory fallback retain execution state and ownership."""

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.agent import AgentRequest
from management.services.agent import run
from management.services.agent.background import BackgroundExecutionState


@pytest.fixture
def generation(monkeypatch):
    request = AgentRequest(query="fixture", agent_id=1, conversation_id=9)
    state = BackgroundExecutionState()
    info = SimpleNamespace()
    prepare = AsyncMock(return_value=(info, None))
    unregister = Mock()
    monkeypatch.setattr(run, "prepare_agent_run", prepare)
    monkeypatch.setattr(run, "_unregister_agent_run_after_execution", unregister)
    monkeypatch.setattr(run, "build_memory_context", lambda *a: SimpleNamespace(
        user_config=SimpleNamespace(memory_switch=True),
    ))

    async def poll(*a):
        await asyncio.Event().wait()

    monkeypatch.setattr(run, "_cancel_task_on_runtime_signal", poll)
    return SimpleNamespace(request=request, state=state, info=info, prepare=prepare, unregister=unregister)


@pytest.mark.asyncio
async def test_background_preparation_failure_sets_explicit_outcome(generation):
    fixture = generation
    fixture.prepare.side_effect = RuntimeError("invalid model configuration")
    chunks = [chunk async for chunk in run.generate_stream(
        fixture.request, "owner", "tenant", execution_state=fixture.state,
    )]
    assert chunks and "error" in chunks[0]
    assert fixture.state.result()["error_code"] == "AUTOMATION_PREPARATION_FAILED"
    assert fixture.state.assistant_message_id is None
    fixture.unregister.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("already_failed", [False, True])
async def test_background_unexpected_stream_failure_releases_prepared_run(monkeypatch, generation, already_failed):
    fixture = generation
    if already_failed:
        fixture.state.fail("SPECIFIC_FAILURE", "Keep the original failure")

    async def stream(**kwargs):
        assert kwargs["execution_state"] is fixture.state
        raise RuntimeError("stream opening failed")
        yield

    monkeypatch.setattr(run, "_stream_agent_chunks", stream)
    chunks = [chunk async for chunk in run.generate_stream(
        fixture.request, "owner", "tenant", execution_state=fixture.state,
    )]
    assert chunks and "error" in chunks[0]
    assert fixture.state.error_code == ("SPECIFIC_FAILURE" if already_failed else "AUTOMATION_EXECUTION_FAILED")
    fixture.unregister.assert_called_once_with(9, "owner", status="failed", agent_run_info=fixture.info)


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_fails", [False, True])
async def test_memory_fallback_carries_background_state_and_reservation(monkeypatch, generation, fallback_fails):
    fixture = generation
    # Capture the real entry point before substituting only its recursive lookup.
    generate = run.generate_stream
    fixture.prepare.side_effect = RuntimeError("memory search failed")
    channel = SimpleNamespace(publish=AsyncMock())

    async def fallback(request, **kwargs):
        assert request is fixture.request
        assert kwargs["enable_memory"] is False
        assert kwargs["execution_state"] is fixture.state
        assert kwargs["reservation_token"] == "owned-reservation"
        assert kwargs["channel"] is channel
        if fallback_fails:
            raise RuntimeError("fallback failed")
        fixture.state.assistant_message_id = 42
        fixture.state.outcome = "completed"
        fixture.state.persisted = True
        yield "fallback output"

    monkeypatch.setattr(run, "generate_stream", fallback)
    chunks = [chunk async for chunk in generate(
        fixture.request, "owner", "tenant", enable_memory=True, channel=channel,
        execution_state=fixture.state, reservation_token="owned-reservation",
    )]
    if fallback_fails:
        assert "error" in chunks[0]
        assert fixture.state.error_message == "Agent execution failed after memory fallback."
        assert fixture.state.result()["status"] == "failed"
    else:
        assert chunks == ["fallback output"]
        assert fixture.state.result()["status"] == "completed"


@pytest.mark.asyncio
async def test_background_without_precreated_prompt_saves_automation_user(monkeypatch, generation):
    fixture = generation
    manager = SimpleNamespace(reserve_agent_run=Mock(return_value="reservation"), release_agent_run_reservation=Mock())
    monkeypatch.setattr(run, "agent_run_manager", manager)
    monkeypatch.setattr(run, "runtime_state_service", SimpleNamespace(reset_stream_async=AsyncMock()))
    monkeypatch.setattr(run, "build_agent_run_context", lambda *a, **k: SimpleNamespace(metadata={}, enable_memory=False))
    monkeypatch.setattr(run, "agent_monitoring_context", lambda *a: nullcontext())
    save = Mock()
    monkeypatch.setattr(run, "save_messages", save)

    async def stream(*a, execution_state, **kwargs):
        assert fixture.request._message_source == "AUTOMATION"
        execution_state.assistant_message_id = 42
        execution_state.outcome = "completed"
        execution_state.persisted = True
        yield "done"

    monkeypatch.setattr(run, "generate_stream", stream)
    result = await run.run_agent_background(fixture.request, "owner", "tenant")
    assert result["status"] == "completed" and result["chunks"] == 1
    save.assert_called_once_with(fixture.request, target="user", user_id="owner", tenant_id="tenant")
    manager.release_agent_run_reservation.assert_called_once_with(9, "owner", "reservation")


def test_generation_specific_stop_never_stops_preprocessing(monkeypatch):
    stop = Mock(return_value=True)
    preprocess = Mock()
    monkeypatch.setattr(run, "agent_run_manager", SimpleNamespace(stop_agent_run=stop))
    monkeypatch.setattr(run, "preprocess_manager", SimpleNamespace(stop_preprocess_tasks=preprocess))
    result = run.stop_agent_tasks(9, "owner", expected_generation="77")
    stop.assert_called_once_with(9, "owner", expected_generation="77")
    preprocess.assert_not_called()
    assert result["status"] == "success"
