from __future__ import annotations

import logging
import sys
import types

import pytest

import consts.const as const
from management.services.agent.management import (
    build_sandbox_policy,
    get_sandbox_minio_client,
)


@pytest.mark.case_id('SEC-AUTO-223E157CE3543948')
@pytest.mark.stage('D5')
def test_sandbox_policy_resolution_and_secure_degradation(monkeypatch, caplog):
    monkeypatch.setattr(const, 'NEXENT_SANDBOX_DEFAULT_LEVEL', 'local')
    assert build_sandbox_policy('tenant_id', 'general') is None

    docker_config = {
        'NEXENT_SANDBOX_DEFAULT_LEVEL': 'docker',
        'NEXENT_SANDBOX_DEFAULT_SCOPE': 'session',
        'NEXENT_SANDBOX_DOCKER_IMAGE': 'nexent/nexent-sandbox:1.2.3-test',
        'NEXENT_SANDBOX_MEMORY_LIMIT_MB': 4096,
        'NEXENT_SANDBOX_CPU_QUOTA': 2.5,
        'NEXENT_SANDBOX_TIMEOUT_S': 120,
        'NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_S': 45.0,
        'NEXENT_SANDBOX_NETWORK_DISABLED': True,
        'NEXENT_SANDBOX_SHELL_POLICY': 'restricted',
        'NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS': False,
    }
    for name, value in docker_config.items():
        monkeypatch.setattr(const, name, value)

    policy = build_sandbox_policy('tenant_id', 'general')
    assert isinstance(policy, dict)
    expected_policy = {
        'level': 'docker',
        'scope': 'session',
        'docker_image': 'nexent/nexent-sandbox:1.2.3-test',
        'memory_limit_mb': 4096,
        'cpu_quota': 2.5,
        'timeout_seconds': 120,
        'host_tool_timeout_seconds': 45.0,
        'network_disabled': True,
        'shell_policy': 'restricted',
        'auto_sync_outputs': False,
    }
    assert set(expected_policy) == set(policy)
    for key, value in expected_policy.items():
        assert policy[key] == value

    monkeypatch.setattr(const, 'NEXENT_SANDBOX_NETWORK_DISABLED', True)
    monkeypatch.setattr(const, 'NEXENT_SANDBOX_SHELL_POLICY', 'disabled')
    policy = build_sandbox_policy('tenant_id', 'general')
    assert policy['network_disabled'] is True
    assert policy['shell_policy'] == 'disabled'

    monkeypatch.setattr(const, 'MINIO_ENDPOINT', '')
    assert get_sandbox_minio_client() is None

    monkeypatch.setattr(const, 'MINIO_ENDPOINT', 'minio.example.internal:9000')
    monkeypatch.setattr(const, 'MINIO_ACCESS_KEY', 'SECRET-ACCESS-MARKER')
    monkeypatch.setattr(const, 'MINIO_SECRET_KEY', 'SECRET-KEY-MARKER')
    monkeypatch.setitem(sys.modules, 'nexent', types.ModuleType('nexent'))
    monkeypatch.setitem(sys.modules, 'nexent.storage', types.ModuleType('nexent.storage'))

    with caplog.at_level(logging.DEBUG):
        assert get_sandbox_minio_client() is None
    assert 'SECRET-ACCESS-MARKER' not in caplog.text
    assert 'SECRET-KEY-MARKER' not in caplog.text
