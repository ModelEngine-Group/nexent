# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.core.agents.sandbox.execution import (
    SandboxConfig, SandboxLevel, SandboxPoolManager, SandboxScope, build_python_executor,
)
from nexent.core.agents.sandbox_contracts import SandboxOwner, SystemSandboxProfile


@pytest.fixture
def pool(mocker):
    mocker.patch.object(SandboxPoolManager, '_start_evictor')
    instance = SandboxPoolManager()
    mocker.patch.object(instance, '_destroy_executor', side_effect=lambda executor, logger: executor.cleanup())
    http = Mock()
    http.post.side_effect = [SimpleNamespace(status_code=201, json=lambda: {'id': 'kernel-a'}),
                            SimpleNamespace(status_code=201, json=lambda: {'id': 'kernel-b'})]
    http.delete.return_value.status_code = 204
    connection = SimpleNamespace(base_url='https://sandbox.namespace.svc:8080', host='sandbox.namespace.svc', port=8080,
                                 tls_client=SimpleNamespace(http=http, ssl_context=Mock()), _nexent_backend='kubernetes',
                                 assert_generation=Mock(), cleanup=Mock(), additional_imports=[], installed_packages=[])
    backend = Mock()
    backend.ensure_system.return_value = connection
    profile = SystemSandboxProfile('sandbox:image', 'claim')
    config = SandboxConfig(level=SandboxLevel.KUBERNETES, scope=SandboxScope.SYSTEM, docker_image='sandbox:image',
                           workspace_mode='bind', container_workspace_root=profile.container_workspace_root,
                           owner=SandboxOwner('release', 'namespace', 'runtime', 'uid', '10.0.0.1', 'epoch'),
                           system_profile=profile, runtime_backend=backend)
    return instance, config, connection, http


def test_individual_kernel_release_or_error_never_deletes_system_owner(pool):
    instance, config, owner, http = pool
    logger = logging.getLogger(__name__)
    left = instance.acquire(config, logger)
    right = instance.acquire(config, logger)
    assert left.kernel_id != right.kernel_id
    assert not hasattr(left, 'container') and left._nexent_backend == 'kubernetes'
    instance.release_immediate(left, logger)
    instance.release(right, logger)
    assert http.delete.call_count == 2
    owner.cleanup.assert_not_called()
    assert not instance._executors and len(instance._system_containers) == 1
    instance.shutdown(logger)
    owner.cleanup.assert_called_once()


def test_startup_cancellation_never_creates_owner(pool):
    instance, config, _, _ = pool
    event = threading.Event()
    event.set()
    from concurrent.futures import CancelledError

    with pytest.raises(CancelledError):
        instance.acquire(config, logging.getLogger(__name__), cancellation_scope=SimpleNamespace(stop_event=event))
    config.runtime_backend.ensure_system.assert_not_called()


@pytest.mark.parametrize('field,value', [('scope', SandboxScope.SESSION), ('owner', None), ('cpu_quota', 2)])
def test_mutated_config_is_rejected_before_constructing_pool(pool, mocker, field, value):
    _, config, _, _ = pool
    factory = mocker.patch.object(SandboxPoolManager, 'get_instance')
    setattr(config, field, value)
    with pytest.raises(ValueError):
        build_python_executor(config, logging.getLogger(__name__))
    factory.assert_not_called()


def test_explicit_local_fallback_requires_a_proved_pre_execution_failure(pool, mocker):
    from nexent.core.agents.sandbox_contracts import SandboxPreExecutionError

    instance, config, owner, http = pool
    config.failure_policy = 'local'
    config.runtime_backend.ensure_system.side_effect = SandboxPreExecutionError('No execution intent')
    local = SimpleNamespace(_nexent_backend='local')
    mocker.patch.object(instance, '_build_executor', return_value=local)
    executor = instance.acquire(config, logging.getLogger(__name__))
    assert executor is local and executor._nexent_backend == 'local'
    assert instance._build_executor.call_args.args[0].level == SandboxLevel.LOCAL
    owner.cleanup.assert_not_called()


@pytest.mark.parametrize('policy,error', [('error', 'proved'), ('local', 'unknown')])
def test_strict_or_uncertain_failures_never_fallback(pool, mocker, policy, error):
    from nexent.core.agents.sandbox_contracts import SandboxPreExecutionError

    instance, config, owner, http = pool
    config.failure_policy = policy
    failure = SandboxPreExecutionError('preflight') if error == 'proved' else OSError('response lost')
    config.runtime_backend.ensure_system.side_effect = failure
    local = mocker.patch.object(instance, '_build_executor')
    with pytest.raises(type(failure)):
        instance.acquire(config, logging.getLogger(__name__))
    local.assert_not_called()
