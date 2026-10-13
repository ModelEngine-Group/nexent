"""Policy precedence and SDK validation at the backend configuration boundary."""

import pytest
from agents.sandbox_config import resolve_sandbox_config
from nexent.core.agents.sandbox import SandboxLevel, SandboxScope


def resolve(db_policy, env_policy):
    return resolve_sandbox_config(
        db_policy, env_policy, workspace_mode='legacy',
        container_workspace_root='', failure_policy='local',
    )


@pytest.mark.parametrize('db_policy', [None, {}])
def test_absent_database_policy_uses_environment(db_policy):
    config = resolve(db_policy, {'level': 'docker', 'scope': 'system'})
    assert config.level == SandboxLevel.DOCKER
    assert config.scope == SandboxScope.SYSTEM


def test_explicit_local_database_policy_overrides_environment():
    config = resolve({'level': 'local'}, {'level': 'docker', 'scope': 'system'})
    assert config.level == SandboxLevel.LOCAL
    assert config.scope == SandboxScope.SESSION


def test_partial_database_policy_uses_sdk_defaults_without_mixing_environment():
    config = resolve({'level': 'docker'}, {'level': 'docker', 'memory_limit_mb': 8192})
    assert config.memory_limit_mb == 2048


def test_database_only_policy():
    assert resolve({'level': 'docker'}, None).level == SandboxLevel.DOCKER


def test_no_policy_preserves_disabled_sandbox():
    assert resolve(None, None) is None


@pytest.mark.parametrize('policy', [{'level': 'invalid'}, {'failure_policy': 'invalid'}, [], 'docker'])
def test_invalid_database_policy_does_not_fall_back(policy):
    with pytest.raises((TypeError, ValueError)):
        resolve(policy, {'level': 'docker'})


def test_agent_workspace_fields_override_deployment_defaults():
    policy = {'level': 'docker', 'workspace_mode': 'legacy', 'failure_policy': 'local'}
    config = resolve_sandbox_config(
        policy, None, workspace_mode='bind', container_workspace_root='/mnt/deployment', failure_policy='error',
    )
    assert config.workspace_mode == 'legacy'
    assert config.failure_policy == 'local'
    assert policy == {'level': 'docker', 'workspace_mode': 'legacy', 'failure_policy': 'local'}


def test_missing_workspace_fields_use_deployment_defaults():
    config = resolve_sandbox_config(
        {'level': 'docker'}, None, workspace_mode='bind', container_workspace_root='/mnt/work', failure_policy='error',
    )
    assert config.workspace_mode == 'bind'
    assert config.container_workspace_root == '/mnt/work'
    assert config.failure_policy == 'error'
