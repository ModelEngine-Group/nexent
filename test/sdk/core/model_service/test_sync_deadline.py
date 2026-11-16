# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""A synchronous call owns an abortable attempt, never the caller's cancellation scope."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event

import pytest

from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.concurrency.manager import ThreadManager
from nexent.core.concurrency.models import LanePolicy, ManagedTaskSpec
from nexent.core.model_service.service import ModelServiceError
from test.sdk.core.model_service.test_model_service import Sender, complete, setup


@pytest.fixture
def manager(monkeypatch):
    manager = ThreadManager("deadline-unit", {"control-io": LanePolicy("control-io", 1, 0)})
    manager.start()
    monkeypatch.setattr("nexent.core.model_service.service.get_current_thread_manager", lambda: manager)
    yield manager
    assert not manager.snapshot().executions
    assert not asyncio.run(manager.shutdown(timeout=2)).stuck_execution_ids


@pytest.mark.parametrize("streaming", [False, True])
def test_deadline_aborts_active_sync_transport_reclaims_permit_and_preserves_parent(setup, manager, caplog, streaming):
    profile, request, limiter, service = setup
    request = request.model_copy(update={"stream": streaming})
    sender, parent = Sender([]), RunCancellationScope()
    closed, scopes = [], []

    def blocked(wire, *, scope):
        sender.calls.append(wire)
        scopes.append(scope)
        stopped = Event()
        token = scope.register_closer(stopped.set)
        try:
            assert stopped.wait(2), "Deadline did not abort the active request"
            raise RunTerminated()
        finally:
            scope.unregister_closer(token)
            closed.append(True)

    @contextmanager
    def stream(wire, *, scope):
        blocked(wire, scope=scope)
        yield iter(())

    sender.invoke, sender.stream = blocked, stream
    start = time.monotonic()
    if streaming:
        with service(sender).stream(request, profile, scope=parent, deadline=start + 0.1) as events:
            error = list(events)[-1].error
    else:
        with pytest.raises(ModelServiceError) as caught:
            service(sender).invoke(request, profile, scope=parent, deadline=start + 0.1)
        error = caught.value.error
    assert error.category == "MODEL_RUN_DEADLINE" and error.attempt == 1 and not error.will_retry
    assert time.monotonic() - start < 1
    assert len(sender.calls) == 1 and closed == [True] and scopes[0].cancelled
    assert not parent.cancelled and not parent._closers and not limiter._entries
    assert [r.message for r in caplog.records] == ["model_request_timeout"]
    assert caplog.records[0].levelname == "WARNING"


def test_completed_call_reaps_watcher_without_late_cancellation(setup, manager):
    profile, request, limiter, service = setup
    sender, parent = Sender([complete()]), RunCancellationScope()
    assert service(sender).invoke(request, profile, scope=parent, deadline=time.monotonic() + 0.1).content_parts
    time.sleep(0.15)
    assert not parent.cancelled and not parent._closers and not limiter._entries
    assert not manager.snapshot().executions


def test_parent_cancel_remains_run_terminated_and_reaps_transport(setup, manager):
    profile, request, limiter, service = setup
    sender, parent, entered = Sender([]), RunCancellationScope(), Event()

    def blocked(wire, *, scope):
        entered.set()
        assert scope.stop_event.wait(2)
        raise RunTerminated()

    sender.invoke = blocked
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service(sender).invoke, request, profile, scope=parent, deadline=time.monotonic() + 2)
        assert entered.wait(1)
        parent.cancel()
        with pytest.raises(RunTerminated):
            future.result(timeout=1)
    assert not limiter._entries and not parent._closers


def test_watcher_capacity_rejects_before_transport_dispatch(setup, manager):
    profile, request, limiter, service = setup
    stop, entered = Event(), Event()

    def occupy():
        entered.set()
        stop.wait(2)

    execution = manager.submit("control-io", ManagedTaskSpec("occupied", "test"), occupy)
    assert entered.wait(1)
    sender = Sender([])
    try:
        with pytest.raises(ModelServiceError) as caught:
            service(sender).invoke(request, profile, deadline=time.monotonic() + 0.1)
        assert caught.value.error.category == "MODEL_CONCURRENCY_TIMEOUT"
        assert not sender.calls and not limiter._entries
    finally:
        stop.set()
        execution.future.result(timeout=1)

