"""HITL outcomes and cancellation must retain managed worker ownership."""

import asyncio
from importlib import import_module
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nexent.core.concurrency import LanePolicy, RunCancellationScope, ThreadManager
from nexent.core.human_interaction.contracts import AttemptSuspended, RecoveryRequired, RunTerminated

run_module = import_module("nexent.core.agents.run_agent")


@pytest.fixture
def execution_fixture(monkeypatch):
    manager = ThreadManager(
        service_name="hitl-test",
        lane_policies={"agent-run": LanePolicy(name="agent-run", max_workers=1, max_queue_size=0)},
    )
    manager.start()
    stop = Event()
    info = SimpleNamespace(
        query="test", observer=MagicMock(lang="en"), agent_config=object(),
        model_config_list=[], mcp_host=[], stop_event=stop, redis_client=None,
        conversation_id=7, user_id="owner", runtime_metadata={}, history=[],
        human_interaction=MagicMock(), attempt_outcome=None, thread_manager=None,
        cancellation_scope=RunCancellationScope(stop),
        mcp_tool_timeout_seconds=1, mcp_close_timeout_seconds=1,
    )
    info.observer.get_cached_message.return_value = []
    agent = SimpleNamespace(tools={})
    nexent = MagicMock()
    nexent.create_single_agent.return_value = agent
    monkeypatch.setattr(run_module, "NexentAgent", MagicMock(return_value=nexent))
    cleanup = MagicMock()
    monkeypatch.setattr(run_module, "cleanup_run_workspace", cleanup)
    collection = MagicMock()
    monkeypatch.setattr(run_module, "ManagedMCPToolCollection", collection)
    yield manager, info, nexent, agent, cleanup, collection
    asyncio.run(manager.shutdown(timeout=2))


@pytest.mark.asyncio
@pytest.mark.parametrize("mcp", [False, True])
@pytest.mark.parametrize("signal,outcome", [
    (None, "completed"),
    (AttemptSuspended, "waiting_human"),
    (RunTerminated, "stopped"),
    (RecoveryRequired, "recovery_required"),
    (ValueError, "failed"),
])
async def test_hitl_worker_outcomes_release_managed_execution(execution_fixture, mcp, signal, outcome):
    manager, info, nexent, agent, cleanup, collection = execution_fixture
    if mcp:
        info.mcp_host = ["http://mcp.invalid/mcp"]
    if signal is not None:
        nexent.agent_run_with_observer.side_effect = signal()

    assert [chunk async for chunk in run_module.agent_run(info, thread_manager=manager)] == []

    info.human_interaction.attach.assert_called_once_with(agent)
    assert info.attempt_outcome == outcome
    assert info.thread_manager is manager
    assert info.thread_future.done()
    cleanup.assert_called_once()
    if mcp:
        assert collection.call_args.kwargs["manager"] is manager
        assert collection.call_args.kwargs["cancellation_scope"] is info.cancellation_scope
        collection.return_value.__exit__.assert_called_once()
    else:
        collection.assert_not_called()
    if outcome == "recovery_required":
        assert any("cannot resume automatically" in str(call) for call in info.observer.add_message.call_args_list)


@pytest.mark.asyncio
async def test_cancelling_hitl_stream_closes_blocked_resource_once(execution_fixture):
    manager, info, nexent, _, cleanup, _ = execution_fixture
    started = Event()
    release = Event()
    close = MagicMock(side_effect=release.set)
    info.cancellation_scope.register_closer(close)

    def blocked_run(**_):
        started.set()
        assert release.wait(5), "Cancellation did not release the blocked tool"

    nexent.agent_run_with_observer.side_effect = blocked_run
    stream = run_module.agent_run(info, thread_manager=manager)
    pending = asyncio.create_task(anext(stream))
    for _ in range(100):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.wait_for(asyncio.wrap_future(info.thread_future), 2)
    info.cancellation_scope.cancel()

    close.assert_called_once()
    assert info.stop_event.is_set()
    assert info.attempt_outcome == "stopped"
    cleanup.assert_called_once()
