# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""T01 establishes identity contracts but never starts an unimplemented backend."""

import logging
from dataclasses import FrozenInstanceError, replace
from unittest.mock import Mock

import pytest

from nexent.core.agents.sandbox.execution import (
    SandboxConfig,
    SandboxLevel,
    SandboxScope,
    build_python_executor,
)
from nexent.core.agents.sandbox_contracts import (
    SandboxBackendUnavailableError,
    SandboxOwner,
)


def test_owner_key_uses_full_pod_uid_and_namespace_not_ip():
    owner = SandboxOwner('release', 'ns', 'runtime', 'uid-a', '10.0.0.1', 'epoch-a')
    assert owner.key == replace(owner, pod_ip='10.0.0.2', epoch='epoch-b').key
    assert owner.key != replace(owner, pod_uid='uid-b').key
    assert owner.key != replace(owner, namespace='other').key
    with pytest.raises(FrozenInstanceError):
        owner.pod_uid = 'changed'


@pytest.mark.parametrize('field,value', [('pod_uid', ''), ('epoch', ''), ('namespace', ''), ('pod_ip', 'not-an-ip')])
def test_incomplete_owner_is_rejected(field, value):
    values = {'deployment_id': 'r', 'namespace': 'ns', 'pod_name': 'p', 'pod_uid': 'u', 'pod_ip': '10.0.0.1', 'epoch': 'e'}
    with pytest.raises(ValueError):
        SandboxOwner(**{**values, field: value})


@pytest.mark.parametrize('failure_policy', ['error', 'local'])
def test_unimplemented_backend_never_constructs_pool_or_local_executor(monkeypatch, failure_policy):
    from nexent.core.agents import sandbox
    pool = Mock(side_effect=AssertionError('Pool must not start'))
    local = Mock(side_effect=AssertionError('Local fallback must not start'))
    monkeypatch.setattr(sandbox.SandboxPoolManager, 'get_instance', pool)
    monkeypatch.setattr(sandbox, '_make_local_executor', local)
    config = SandboxConfig(level=SandboxLevel.KUBERNETES, scope=SandboxScope.SYSTEM, failure_policy=failure_policy)
    with pytest.raises(SandboxBackendUnavailableError, match='T02'):
        build_python_executor(config, logging.getLogger(__name__))
    pool.assert_not_called()
    local.assert_not_called()
