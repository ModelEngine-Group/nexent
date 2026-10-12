import threading

import pytest
from nexent.core.concurrency import RunCancellationScope
from nexent.core.concurrency.cancellation import RunCancellationScope as ModuleScope


@pytest.mark.parametrize("explicit_local", [False, True])
def test_SAI_D1_007_constructor_and_parent_propagation(explicit_local):
    original_threads = {thread.ident for thread in threading.enumerate()}
    assert RunCancellationScope is ModuleScope
    legacy_event = threading.Event()
    legacy = RunCancellationScope(legacy_event)
    assert legacy.stop_event is legacy_event
    legacy.cancel()
    assert legacy_event.is_set()

    parent = threading.Event()
    local = threading.Event() if explicit_local else None
    child = RunCancellationScope(local, parent_stop_event=parent)
    sibling = RunCancellationScope(parent_stop_event=parent)
    closed = []
    sibling.register_closer(lambda: closed.append("sibling"))
    assert not sibling.stop_event.wait(0)
    assert not sibling.stop_event.wait(0.01)
    child.cancel()
    assert child.cancelled
    assert not parent.is_set()
    assert not sibling.cancelled
    if local is not None:
        assert local.is_set()

    ready = threading.Event()
    observed = []

    def wait_for_stop():
        ready.set()
        observed.append(sibling.stop_event.wait(2))

    waiter = threading.Thread(target=wait_for_stop)
    waiter.start()
    try:
        assert ready.wait(1)
        parent.set()
        waiter.join(1)
        assert not waiter.is_alive()
        assert observed == [True]
        assert sibling.cancelled
        sibling.cancel()
        assert closed == ["sibling"]
        sibling.register_closer(lambda: closed.append("late"))
        assert closed == ["sibling", "late"]
        sibling.stop_event.clear()
        assert sibling.stop_event.is_set()
    finally:
        parent.set()
        waiter.join(2)
    assert {thread.ident for thread in threading.enumerate()} == original_threads


pytestmark = [pytest.mark.case_id("SAI-D1-007"), pytest.mark.stage("D1")]
