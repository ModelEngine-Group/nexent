import threading

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


def test_ut_sdk_tlm_024_resource_registered_after_cancel_closes_immediately():
    scope = RunCancellationScope(threading.Event())
    closed = []
    scope.cancel()

    token = scope.register_closer(lambda: closed.append("closed"))
    scope.unregister_closer(token)

    assert closed == ["closed"]
