"""Stopping a consumer must not wait for an unresponsive provider worker."""

import asyncio
import importlib
import threading

import pytest

from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.utils.observer import MessageObserver


@pytest.mark.asyncio
async def test_stop_signal_closes_consumer_before_blocked_worker_finishes(monkeypatch):
    module = importlib.import_module("nexent.core.agents.run_agent")
    entered, release = threading.Event(), threading.Event()

    def provider_worker(_run_info):
        entered.set()
        release.wait(5)

    monkeypatch.setattr(module, "agent_run_thread", provider_worker)
    manager = ThreadManager("cancel-controls-ut", {"agent-run": LanePolicy(
        name="agent-run", max_workers=1, max_queue_size=1, cancel_grace_seconds=0.1,
        shutdown_grace_seconds=1)})
    manager.start()
    info = AgentRunInfo(query="fixture", model_config_list=[],
                        agent_config=AgentConfig(name="fixture", description="", tools=[], model_name="fixture"),
                        observer=MessageObserver(lang="en"), history=[], stop_event=threading.Event())

    async def consume():
        return [event async for event in module.agent_run(info, thread_manager=manager)]

    task = asyncio.create_task(consume())
    try:
        async with asyncio.timeout(1):
            while not entered.is_set():
                await asyncio.sleep(0.01)
        info.stop_event.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert not release.is_set()
        assert info.cancellation_scope.cancelled
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await manager.shutdown(timeout=2)
