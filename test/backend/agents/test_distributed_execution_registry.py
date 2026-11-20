# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.executions import AgentRunAlreadyActiveError, LocalExecutionRegistry
from runtime.sandbox_coordination import SandboxRunBusy


@pytest.fixture
def registry():
    class IsolatedRegistry(LocalExecutionRegistry):
        pass

    instance = IsolatedRegistry()
    coordinator = Mock()
    coordinator.reserve.return_value = SimpleNamespace(token='capability', run_id='a' * 32)
    instance.configure_coordinator(coordinator)
    return instance, coordinator


def reserve(instance):
    return instance.reserve_agent_run(1, 'user', tenant_id='tenant', execution_run_id='a' * 32)


def test_distributed_lease_survives_consumed_local_reservation_until_worker_done(registry):
    instance, coordinator = registry
    token = reserve(instance)
    info = SimpleNamespace(thread_future=Future())
    instance.register_agent_run(1, info, 'user', token)
    coordinator.activate.assert_called_once_with(coordinator.reserve.return_value)
    assert not instance.release_agent_run_reservation(1, 'user', token)
    assert not instance.unregister_agent_run(1, 'user', agent_run_info=info)
    coordinator.finish.assert_not_called()
    assert instance.get_active_run_count() == 1
    info.thread_future.set_result(None)
    coordinator.finish.assert_called_once_with(coordinator.reserve.return_value)
    assert instance.get_active_run_count() == 0


def test_completion_between_done_and_callback_attachment_does_not_deadlock(registry):
    instance, coordinator = registry
    token = reserve(instance)
    future = Mock()
    future.done.side_effect = [False, True]
    future.add_done_callback.side_effect = lambda callback: callback(future)
    info = SimpleNamespace(thread_future=future)
    instance.register_agent_run(1, info, 'user', token)
    assert not instance.unregister_agent_run(1, 'user', agent_run_info=info)
    coordinator.finish.assert_called_once()
    assert instance.get_active_run_count() == 0


def test_activation_failure_preserves_reservation_for_exact_cleanup(registry):
    instance, coordinator = registry
    token = reserve(instance)
    coordinator.activate.side_effect = RuntimeError('coordination lost')
    with pytest.raises(RuntimeError, match='lost'):
        instance.register_agent_run(1, SimpleNamespace(), 'user', token)
    assert instance.release_agent_run_reservation(1, 'user', token)
    coordinator.finish.assert_called_once()


def test_remote_conflict_does_not_create_local_reservation(registry):
    instance, coordinator = registry
    coordinator.reserve.side_effect = SandboxRunBusy('active')
    with pytest.raises(AgentRunAlreadyActiveError):
        reserve(instance)
    assert not instance._reservations


def test_missing_trusted_identity_and_unreserved_registration_are_rejected(registry):
    instance, coordinator = registry
    with pytest.raises(RuntimeError, match='trusted'):
        instance.reserve_agent_run(1, 'user')
    coordinator.reserve.assert_not_called()
    with pytest.raises(AgentRunAlreadyActiveError):
        instance.register_agent_run(1, SimpleNamespace(), 'user')


def test_wrong_reservation_token_and_stale_info_cannot_release_owner(registry):
    instance, coordinator = registry
    token = reserve(instance)
    assert not instance.release_agent_run_reservation(1, 'user', 'wrong')
    info = SimpleNamespace(thread_future=None)
    instance.register_agent_run(1, info, 'user', token)
    assert not instance.unregister_agent_run(1, 'user', agent_run_info=SimpleNamespace())
    coordinator.finish.assert_not_called()
    assert instance.unregister_agent_run(1, 'user', agent_run_info=info)
