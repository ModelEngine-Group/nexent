# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Kubernetes policy normalization never changes stored Agent policy."""

import logging
from copy import deepcopy
from dataclasses import replace

import pytest
from nexent.core.agents.sandbox.execution import SandboxLevel, SandboxScope
from nexent.core.agents.sandbox_contracts import SandboxOwner, SystemSandboxProfile
from runtime.adapters.nexent import sandbox
from runtime.adapters.nexent.sandbox import resolve_sandbox_config


@pytest.fixture
def deployment():
    return {
        'provider': 'kubernetes',
        'owner': SandboxOwner('release', 'ns', 'runtime-a', 'uid-a', '10.0.0.1', 'epoch-a'),
        'system_profile': SystemSandboxProfile('sandbox:fixed', workspace_volume='workspace'),
        'workspace_mode': 'bind',
        'container_workspace_root': '/mnt/nexent/workdir',
        'failure_policy': 'error',
    }


@pytest.mark.parametrize('policy', [None, {}, {'level': 'docker'}, {'level': 'kubernetes'}])
def test_kubernetes_defaults_are_system_and_error_without_mutation(deployment, policy):
    original = deepcopy(policy)
    config = resolve_sandbox_config(policy, None, **deployment)
    assert config.level == SandboxLevel.KUBERNETES
    assert config.scope == SandboxScope.SYSTEM
    assert config.failure_policy == 'error'
    assert config.execution_image == 'sandbox:fixed'
    assert config.owner is deployment['owner']
    assert config.system_profile is deployment['system_profile']
    assert policy == original


def test_deployed_sandbox_uses_runtime_identity_and_profile(deployment, mocker):
    options = {key: deployment[key] for key in ("provider", "owner", "system_profile")}
    mocker.patch.object(sandbox, "get_runtime_sandbox_options", return_value=options)
    mocker.patch.object(sandbox, "default_sandbox_policy", return_value={"level": "kubernetes"})
    mocker.patch.object(sandbox.environment, "NEXENT_SANDBOX_WORKSPACE_MODE", "bind")
    mocker.patch.object(sandbox.environment, "NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT", "/mnt/nexent/workdir")
    mocker.patch.object(sandbox.environment, "NEXENT_SANDBOX_FAILURE_POLICY", "error")

    config = sandbox.resolve_deployed_sandbox(None)

    assert config.level == SandboxLevel.KUBERNETES
    assert config.owner is deployment["owner"]
    assert config.system_profile is deployment["system_profile"]


@pytest.mark.parametrize('level', ['local', 'wasm'])
def test_explicit_non_container_policy_keeps_its_semantics(deployment, level):
    config = resolve_sandbox_config({'level': level}, {'level': 'docker'}, **deployment)
    assert config.level.value == level
    assert config.owner is None
    assert config.scope == SandboxScope.SESSION


def test_disabled_deployment_does_not_resolve_remote_policy(deployment):
    assert resolve_sandbox_config({'level': 'docker'}, None, enabled=False, **deployment) is None


def test_session_is_rejected_without_fallback(deployment):
    with pytest.raises(ValueError, match='SESSION'):
        resolve_sandbox_config({'level': 'docker', 'scope': 'session'}, None, **deployment)


@pytest.mark.parametrize('field,value', [
    ('docker_image', 'other:tag'), ('memory_limit_mb', 4096),
    ('cpu_quota', 2), ('network_disabled', False), ('workspace_mode', 'legacy'),
    ('container_workspace_root', '/other'),
    ('execution_uid', 0), ('execution_gid', 0), ('tls_enabled', False),
    ('workspace_volume', 'other-claim'),
])
def test_pod_profile_conflicts_are_rejected(deployment, field, value):
    with pytest.raises(ValueError, match='profile'):
        resolve_sandbox_config({'level': 'docker', field: value}, None, **deployment)


def test_call_policy_does_not_conflict_with_fixed_pod(deployment):
    config = resolve_sandbox_config({
        'level': 'docker', 'timeout_seconds': 7, 'host_tool_timeout_seconds': 11,
        'shell_policy': 'boxed', 'auto_sync_outputs': False, 'failure_policy': 'local',
        'owner': {'pod_uid': 'attacker'},
    }, {'level': 'docker', 'timeout_seconds': 99}, **deployment)
    assert config.timeout_seconds == 7
    assert config.host_tool_timeout_seconds == 11
    assert config.shell_policy.value == 'boxed'
    assert config.auto_sync_outputs is False
    assert config.failure_policy == 'local'
    assert config.owner.pod_uid == 'uid-a'


def test_incomplete_trusted_identity_or_profile_is_rejected(deployment):
    for field in ('owner', 'system_profile'):
        with pytest.raises(ValueError, match='trusted'):
            resolve_sandbox_config({'level': 'docker'}, None, **{**deployment, field: None})


def test_profile_digest_is_stable_and_changes_only_with_pod_settings(deployment):
    profile = deployment['system_profile']
    assert profile.fingerprint == replace(profile).fingerprint
    assert profile.fingerprint != replace(profile, memory_limit_mb=4096).fingerprint
    assert profile.fingerprint == replace(profile, cpu_quota=1).fingerprint


@pytest.mark.parametrize('field,value', [
    ('memory_limit_mb', 0), ('memory_limit_mb', True), ('cpu_quota', float('nan')),
    ('cpu_quota', float('inf')), ('cpu_quota', 0), ('execution_uid', True),
    ('network_disabled', 'false'), ('tls_enabled', False),
])
def test_invalid_deployment_profile_cannot_be_used(deployment, field, value):
    with pytest.raises(ValueError):
        replace(deployment['system_profile'], **{field: value})


def test_image_alias_conflict_is_not_silently_resolved(deployment):
    with pytest.raises(ValueError, match='image'):
        resolve_sandbox_config({'level': 'docker', 'docker_image': 'a', 'execution_image': 'b'}, None, **deployment)


def test_conversion_log_distinguishes_original_policy_from_effective_backend(deployment, caplog):
    with caplog.at_level(logging.INFO, logger='runtime.adapters.nexent.sandbox'):
        resolve_sandbox_config({'level': 'docker'}, None, **deployment)
    assert 'original_level=docker provider=kubernetes effective_level=kubernetes' in caplog.text
    assert deployment['system_profile'].fingerprint in caplog.text


@pytest.mark.parametrize('provider', ['typo', '', 'local'])
def test_unknown_provider_is_rejected(deployment, provider):
    with pytest.raises(ValueError, match='provider'):
        resolve_sandbox_config(None, None, **{**deployment, 'provider': provider})


def test_complete_docker_policy_does_not_validate_unused_environment_policy():
    config = resolve_sandbox_config(
        {'level': 'docker'}, ['unused'], workspace_mode='legacy',
        container_workspace_root='', failure_policy='local',
    )
    assert config.level == SandboxLevel.DOCKER
    assert config.scope == SandboxScope.SESSION
