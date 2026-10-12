"""SAI-D1-002: case-local preserved component regression."""
import threading
from concurrent.futures import CancelledError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents import sandbox
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency import ManagedTaskSpec
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from shared.sai_component import (
    ORIGINAL_SANDBOX_CLEANUP as ORIGINAL_SANDBOX_CLEANUP,
)
from shared.sai_component import (
    manager as manager,
)
from shared.sai_component import (
    setup_factory as setup_factory,
)


def test_SAI_D1_002_lifecycle(setup_factory, monkeypatch, manager):
    factory, child, _, cleaned, _ = setup_factory
    with pytest.raises(ValueError, match='controlled task failure'):
        child(task='FAIL')
    assert len(cleaned) == 1
    original = NexentAgent.create_single_agent

    def fail_construction(self, config, **kwargs):
        self._sandbox_executors.append(object())
        raise ValueError('partial allocation')

    monkeypatch.setattr(NexentAgent, 'create_single_agent', fail_construction)
    with pytest.raises(ValueError, match='partial allocation'):
        child(task='construct')
    assert len(cleaned) == 2 and len(cleaned[-1]._sandbox_executors) == 1
    monkeypatch.setattr(NexentAgent, 'create_single_agent', original)
    started = threading.Event()
    monkeypatch.setattr(NexentAgent, 'create_model', lambda self, name: SimpleNamespace(started=started))
    execution = manager.submit('model-tool-io', ManagedTaskSpec('owned-child', 'test'), child, task='WAIT')
    assert started.wait(5)
    factory._close_subagent_invocations()
    assert execution.future.result(timeout=5)['task'] == 'WAIT'
    assert not factory._subagent_invocations
    with pytest.raises(RunTerminated):
        child(task='late')
    assert len(cleaned) == 3

    stuck = threading.Event()
    factory._subagent_invocations[stuck] = RunCancellationScope()
    with pytest.raises(RuntimeError, match='did not terminate'):
        factory._close_subagent_invocations(timeout=0)
    assert len(cleaned) == 3
    factory._subagent_invocations.clear()

    factory._subagent_invocations_closed = False
    original_close = NexentAgent._close_subagent_invocations

    def nested_stuck(owner, timeout=5):
        raise RuntimeError('nested invocation did not terminate')

    monkeypatch.setattr(NexentAgent, '_close_subagent_invocations', nested_stuck)
    with pytest.raises(RuntimeError, match='nested invocation'):
        child(task='nested')
    assert len(factory._subagent_invocations) == 1
    assert len(cleaned) == 3
    with pytest.raises(RuntimeError, match='did not terminate'):
        original_close(factory, timeout=0)
    factory._subagent_invocations.clear()
    monkeypatch.setattr(NexentAgent, '_close_subagent_invocations', original_close)

    lease = Mock(_nexent_kernel_lease=True)
    cleanup_manager = Mock()
    cleanup_manager.run_sync.side_effect = RuntimeError('cleanup failure')
    monkeypatch.setattr(sandbox, '_get_sandbox_thread_manager', lambda: cleanup_manager)
    sandbox.cleanup_executor(lease, Mock())
    lease.container.kill.assert_not_called()

    channel = Mock()
    cancelled = RunCancellationScope()
    raw = object.__new__(sandbox._DockerKernelLease)
    raw._cancellation_scope = cancelled
    raw._closed = False
    raw._unhealthy = False
    raw.ws_url = 'ws://logical-gateway/channels'
    raw._ssl_context = None
    raw._receive_timeout_seconds = 1
    monkeypatch.setattr('websocket.create_connection', lambda *args, **kwargs: channel)
    channel.getstatus.return_value = 101
    raw._wait_for_kernel_channel_ready = lambda ws: None

    def interrupted(*args, **kwargs):
        from websocket import WebSocketConnectionClosedException

        cancelled.cancel()
        raise WebSocketConnectionClosedException('closed by cancellation')

    channel.recv_data.side_effect = interrupted
    with pytest.raises(CancelledError):
        raw.run_code_raise_errors('controlled execution')
    channel.shutdown.assert_called_once()
    channel.close.assert_called_once()
    assert raw._unhealthy is False


pytestmark = [pytest.mark.case_id("SAI-D1-002"), pytest.mark.stage("D1")]
