import threading
from unittest.mock import Mock

import pytest
from nexent.core.concurrency import RunCancellationScope


def test_ut_sdk_tlm_024_cancel_closes_registered_resource_once():
    stop_event = threading.Event()
    closed = []
    scope = RunCancellationScope(stop_event)
    scope.register_closer(lambda: closed.append("closed"))

    scope.cancel()
    scope.cancel()

    assert stop_event.is_set()
    assert closed == ["closed"]


@pytest.mark.parametrize("explicit_local", [False, True])
def test_parent_linked_scope_keeps_child_cancellation_local(mocker, explicit_local):
    parent = threading.Event()
    local = threading.Event() if explicit_local else None
    left = RunCancellationScope(local, parent_stop_event=parent)
    right = RunCancellationScope(parent_stop_event=parent)
    closer = Mock()
    right.register_closer(closer)
    left.cancel()
    assert left.cancelled and not parent.is_set()
    assert not right.stop_event.wait(0.01) and not right.cancelled
    if local is not None:
        assert local.is_set()
    parent.set()
    assert right.stop_event.wait(0.1) and right.cancelled
    right.cancel()
    closer.assert_called_once()
    right.stop_event.clear()
    assert right.stop_event.is_set()


def test_parent_already_stopped_closes_new_child_resources(mocker):
    parent = threading.Event()
    parent.set()
    child = RunCancellationScope(parent_stop_event=parent)
    closer = Mock()
    child.register_closer(closer)
    assert child.cancelled and child.stop_event.wait(0)
    child.cancel()
    closer.assert_called_once()


def test_ut_sdk_tlm_024_resource_registered_after_cancel_closes_immediately():
    scope = RunCancellationScope(threading.Event())
    closed = []
    scope.cancel()

    token = scope.register_closer(lambda: closed.append("closed"))
    scope.unregister_closer(token)

    assert closed == ["closed"]


def test_public_constructor_keeps_legacy_event_identity():
    from nexent.core.concurrency.cancellation import RunCancellationScope as ModuleScope

    assert RunCancellationScope is ModuleScope
    event = threading.Event()
    scope = RunCancellationScope(event)
    assert scope.stop_event is event
    scope.cancel()
    assert event.is_set()


def test_parent_stop_wakes_blocked_waiter_without_background_watchers():
    original_threads = {thread.ident for thread in threading.enumerate()}
    parent = threading.Event()
    scope = RunCancellationScope(parent_stop_event=parent)
    ready = threading.Event()
    observed = []

    def wait_for_stop():
        ready.set()
        observed.append(scope.stop_event.wait(2))

    waiter = threading.Thread(target=wait_for_stop)
    waiter.start()
    try:
        assert ready.wait(1)
        parent.set()
        waiter.join(1)
        assert not waiter.is_alive()
        assert observed == [True]
    finally:
        parent.set()
        waiter.join(2)
    assert {thread.ident for thread in threading.enumerate()} == original_threads
