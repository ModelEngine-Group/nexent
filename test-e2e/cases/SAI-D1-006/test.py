"""SAI-D1-006: case-local preserved component regression."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency import ManagedTaskSpec
from nexent.core.concurrency.cancellation import RunCancellationScope
from shared.sai_component import (
    ORIGINAL_SANDBOX_CLEANUP as ORIGINAL_SANDBOX_CLEANUP,
)
from shared.sai_component import (
    manager as manager,
)
from shared.sai_component import (
    setup_factory as setup_factory,
)


def test_SAI_D1_006_event_only_stop(setup_factory, monkeypatch, manager):
    factory, child, _, _, _ = setup_factory
    factory.cancellation_scope = None
    started = threading.Event()
    monkeypatch.setattr(NexentAgent, 'create_model', lambda self, name: SimpleNamespace(started=started))
    execution = manager.submit('model-tool-io', ManagedTaskSpec('event-only-child', 'test'), child, task='WAIT')
    try:
        assert started.wait(2)
        factory.stop_event.set()
        assert execution.future.result(timeout=0.5)['task'] == 'WAIT'
    finally:
        factory._close_subagent_invocations()

    parent_event = threading.Event()
    left = RunCancellationScope(parent_stop_event=parent_event)
    right = RunCancellationScope(parent_stop_event=parent_event)
    left_close, right_close = Mock(), Mock()
    left.register_closer(left_close)
    right.register_closer(right_close)
    left.cancel()
    assert left.cancelled and not parent_event.is_set()
    assert not right.cancelled and not right.stop_event.is_set()
    left_close.assert_called_once()
    right_close.assert_not_called()
    parent_event.set()
    assert right.stop_event.wait(0.5) and right.cancelled
    right_close.assert_called_once()
    right.cancel()
    right_close.assert_called_once()


pytestmark = [pytest.mark.case_id("SAI-D1-006"), pytest.mark.stage("D1")]
