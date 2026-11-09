# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Jiuwen invocations share an owned loop without serializing whole runs."""

import asyncio
from contextvars import ContextVar
from threading import Event
from types import SimpleNamespace

import pytest

from nexent.core.agents.contracts.config import AgentConfig
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, RunCancellationScope, ThreadManager
from nexent.core.utils.observer import MessageObserver


@pytest.fixture
def manager():
    owner = ThreadManager("jiuwen-loop-ut", {
        name: LanePolicy(name=name, max_workers=4, max_queue_size=8)
        for name in ("agent-run", "background-service")
    })
    owner.start()
    yield owner
    result = asyncio.run(owner.shutdown(timeout=5))
    assert not result.stuck_execution_ids
    assert owner.snapshot().active_count == 0


def adapter_for(manager):
    stop = Event()
    info = SimpleNamespace(agent_config=AgentConfig(name="fixture", description="Fixture", model_name="fixture", tools=[]),
                           observer=MessageObserver(), stop_event=stop, thread_manager=manager)
    adapter = JiuwenAdapter(info)
    adapter.manager = manager
    adapter.scope = RunCancellationScope(stop)
    return adapter


def submit(manager, callback):
    return manager.submit("agent-run", ManagedTaskSpec(task_name="loop-test", owner=__name__), callback)


def test_parallel_registration_and_repeated_runs_keep_one_loop_and_invocation_context(manager):
    lock = asyncio.Lock()
    invocation = ContextVar("invocation", default=None)
    loops, contexts = [], []

    def invoke(index):
        token = invocation.set(index)
        adapter = adapter_for(manager)

        async def run():
            loops.append(id(asyncio.get_running_loop()))
            # A finite wait also makes the old cross-loop defect terminate safely.
            await asyncio.wait_for(lock.acquire(), timeout=1)
            try:
                await asyncio.sleep(0.01)
                contexts.append(invocation.get())
            finally:
                lock.release()
            adapter.events.final_answer = str(index)
            return str(index)

        adapter._run_async = run
        try:
            return adapter.run()
        finally:
            invocation.reset(token)

    for batch in range(3):
        executions = [submit(manager, lambda index=i: invoke(index)) for i in range(batch * 3, batch * 3 + 3)]
        assert [e.future.result(timeout=5) for e in executions] == list(map(str, range(batch * 3, batch * 3 + 3)))
    assert len(set(loops)) == 1
    assert sorted(contexts) == list(range(9))


def test_cancelling_one_invocation_waits_for_its_cleanup_and_keeps_its_sibling_alive(manager):
    entered, cleaned, sibling_started = Event(), Event(), Event()
    stopped, sibling = adapter_for(manager), adapter_for(manager)

    async def blocked():
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        token = stopped.scope.register_closer(lambda: loop.call_soon_threadsafe(task.cancel))
        entered.set()
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0.02)
            cleaned.set()
            stopped.scope.unregister_closer(token)

    async def independent():
        sibling_started.set()
        await asyncio.sleep(0.1)
        sibling.events.final_answer = "sibling"
        return "sibling"

    stopped._run_async, sibling._run_async = blocked, independent
    first, second = submit(manager, stopped.run), submit(manager, sibling.run)
    assert entered.wait(3) and sibling_started.wait(3)
    stopped.scope.cancel()
    with pytest.raises(BaseException) as error:
        first.future.result(timeout=3)
    from nexent.core.concurrency.cancellation import RunTerminated
    assert isinstance(error.value, RunTerminated)
    assert cleaned.is_set()
    assert second.future.result(timeout=3) == "sibling"


def test_whole_invocations_overlap_instead_of_waiting_for_a_global_run_lock(manager):
    from nexent.core.agents.cores.jiuwen.execution_loop import get_execution_loop

    owner = get_execution_loop(manager)
    entered, release = [], asyncio.Event()

    async def work(index):
        entered.append(index)
        if len(entered) == 3:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=1)
        return index

    runs = [submit(manager, lambda i=i: owner.run(lambda: work(i))) for i in range(3)]
    assert [run.future.result(3) for run in runs] == [0, 1, 2]


def test_failure_and_terminal_clarification_keep_their_types_without_stopping_service(manager):
    from nexent.core.agents.contracts.clarification import ClarificationForm
    from nexent.core.agents.cores.jiuwen.clarification import ClarificationRequested
    from nexent.core.agents.cores.jiuwen.execution_loop import get_execution_loop

    owner = get_execution_loop(manager)
    form = ClarificationForm.model_validate({"questions": [{"id": "info", "type": "text", "title": "Info"}]})

    async def fail(error):
        raise error

    with pytest.raises(ValueError, match="fixture failure"):
        owner.run(lambda: fail(ValueError("fixture failure")))
    with pytest.raises(ClarificationRequested) as paused:
        owner.run(lambda: fail(ClarificationRequested(form)))
    assert paused.value.form == form
    assert owner.run(lambda: asyncio.sleep(0, result="healthy")) == "healthy"


def test_shutdown_cancels_owned_tasks_and_waits_for_cleanup_before_thread_finishes(manager):
    from nexent.core.agents.cores.jiuwen.execution_loop import get_execution_loop

    owner = get_execution_loop(manager)
    entered, cleaned, cancelled = Event(), Event(), Event()

    async def blocked():
        entered.set()
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0.02)
            cleaned.set()

    run = submit(manager, lambda: owner.run(blocked, cancel=cancelled.set))
    assert entered.wait(3)
    owner.stop()
    owner.execution.future.result(timeout=4)
    with pytest.raises(asyncio.CancelledError):
        run.future.result(timeout=3)
    assert cleaned.is_set() and cancelled.is_set()
    from nexent.core.concurrency.cancellation import RunTerminated
    with pytest.raises(RunTerminated):
        owner.run(blocked)


def test_same_loop_sync_reentry_fails_instead_of_deadlocking(manager):
    from nexent.core.agents.cores.jiuwen.execution_loop import get_execution_loop

    owner = get_execution_loop(manager)

    async def reenter():
        with pytest.raises(RuntimeError, match="own execution loop"):
            owner.run(lambda: asyncio.sleep(0))
        return "not blocked"

    assert owner.run(reenter) == "not blocked"


def test_service_start_failure_is_reported_without_starting_the_invocation(manager, monkeypatch):
    from nexent.core.agents.cores.jiuwen.execution_loop import JiuwenExecutionLoop
    from nexent.core.concurrency.cancellation import RunTerminated

    async def fail_start(self, cancel_event):
        raise ValueError("startup fixture")

    monkeypatch.setattr(JiuwenExecutionLoop, "_serve_async", fail_start)
    owner = JiuwenExecutionLoop(manager)
    with pytest.raises(RunTerminated) as failed:
        owner.run(lambda: asyncio.sleep(0))
    assert isinstance(failed.value.__cause__, ValueError)


def test_service_capacity_rejection_never_creates_an_unmanaged_fallback(manager):
    from nexent.core.agents.cores.jiuwen.execution_loop import JiuwenExecutionLoop
    from nexent.core.concurrency import ManagedThreadSpec, ThreadCapacityExceeded

    for i in range(4):
        execution = manager.register_service(
            ManagedThreadSpec(task_name=f"occupied-{i}", owner=__name__), lambda cancelled: cancelled.wait())
        manager.start_service(execution.execution_id)
    with pytest.raises(ThreadCapacityExceeded):
        JiuwenExecutionLoop(manager)
    assert all(x.task_name != "jiuwen-execution-loop" for x in manager.snapshot().executions)


def test_process_service_does_not_retain_the_first_request_context(manager, monkeypatch):
    from nexent.core.agents.cores.jiuwen.execution_loop import JiuwenExecutionLoop, get_execution_loop

    identity = ContextVar("request-identity", default=None)
    service_values = []
    serve = JiuwenExecutionLoop._serve_async

    async def observe(self, cancelled):
        service_values.append(identity.get())
        return await serve(self, cancelled)

    monkeypatch.setattr(JiuwenExecutionLoop, "_serve_async", observe)
    token = identity.set("request-only")
    try:
        owner = get_execution_loop(manager)

        async def invocation():
            return identity.get()

        assert owner.run(invocation) == "request-only"
        assert service_values == [None]
    finally:
        identity.reset(token)
