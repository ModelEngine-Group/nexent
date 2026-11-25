# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolve per-agent sandbox policy without reading deployment environment."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from contracts.constants import environment
from infrastructure.sandbox_deployment import default_sandbox_policy
from nexent.core.agents.sandbox.config import SandboxConfig

if TYPE_CHECKING:
    from nexent.core.agents.sandbox_contracts import SandboxOwner, SystemSandboxProfile

logger = logging.getLogger(__name__)


def resolve_deployed_sandbox(database_policy: dict[str, Any] | None) -> SandboxConfig | None:
    return resolve_sandbox_config(
        database_policy,
        default_sandbox_policy(),
        workspace_mode=environment.NEXENT_SANDBOX_WORKSPACE_MODE,
        container_workspace_root=environment.NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT,
        failure_policy=environment.NEXENT_SANDBOX_FAILURE_POLICY,
        **get_runtime_sandbox_options(),
    )


def resolve_sandbox_config(
    database_policy: dict[str, Any] | None,
    environment_policy: dict[str, Any] | None,
    *,
    workspace_mode: str,
    container_workspace_root: str,
    failure_policy: str,
    provider: str = "docker",
    owner: SandboxOwner | None = None,
    system_profile: SystemSandboxProfile | None = None,
    enabled: bool = True,
) -> SandboxConfig | None:
    """Use a complete DB policy first; omitted policy fields retain SDK defaults.

    Workspace deployment values are defaults that explicit policy fields override.
    Empty DB objects represent an unconfigured policy, not an explicit local level.
    """
    if provider not in {"docker", "kubernetes"}:
        raise ValueError("Unknown sandbox deployment provider")
    if not enabled:
        return None
    if database_policy is not None and not isinstance(database_policy, dict):
        raise TypeError("Agent sandbox policy must be a dictionary")
    if not database_policy and environment_policy is not None and not isinstance(environment_policy, dict):
        raise TypeError("Deployment sandbox policy must be a dictionary")
    policy = deepcopy(database_policy or environment_policy)
    if provider != 'kubernetes' and policy and policy.get('level') == 'kubernetes':
        raise ValueError("Kubernetes sandbox requires the kubernetes deployment provider")
    if provider == "kubernetes" and (not policy or policy.get("level", "docker") in {"docker", "kubernetes"}):
        from nexent.core.agents.sandbox_contracts import (
            SandboxOwner,
            SystemSandboxProfile,
        )

        if not isinstance(owner, SandboxOwner) or not isinstance(system_profile, SystemSandboxProfile):
            raise ValueError("Kubernetes sandbox requires a trusted owner and SYSTEM profile")
        policy = policy or {}
        original_level = policy.get('level', 'unset')
        for name in ('execution_uid', 'execution_gid', 'tls_enabled', 'workspace_volume'):
            if name in policy and policy[name] != getattr(system_profile, name):
                raise ValueError(f"Sandbox SYSTEM profile conflict: {name}")
        if 'network_disabled' in policy and type(policy['network_disabled']) is not bool:
            raise ValueError("Sandbox profile network_disabled must be a boolean")
        if 'execution_image' in policy:
            if 'docker_image' in policy and policy['docker_image'] != policy['execution_image']:
                raise ValueError("Conflicting sandbox image aliases")
            policy['docker_image'] = policy.pop('execution_image')
        policy = {
            **system_profile.policy_defaults(),
            'scope': 'system',
            'failure_policy': failure_policy,
            **policy,
            'level': 'kubernetes',
        }
        config = SandboxConfig.from_dict(policy)
        system_profile.validate_config(config)
        config.owner = owner
        config.system_profile = system_profile
        logger.info(
            'Sandbox policy original_level=%s provider=%s effective_level=%s profile=%s',
            original_level, provider, config.level.value, system_profile.fingerprint,
        )
        return config
    return (
        SandboxConfig.from_dict(
            {
                "workspace_mode": workspace_mode,
                "container_workspace_root": container_workspace_root,
                "failure_policy": failure_policy,
                **policy,
            }
        )
        if policy
        else None
    )


def get_runtime_sandbox_options() -> dict[str, Any]:
    """Inject deployment constants; the SDK never reads process environment."""
    from contracts.constants import environment as settings

    provider = getattr(settings, 'NEXENT_SANDBOX_PROVIDER', 'docker')
    if provider == 'docker':
        return {} if getattr(settings, 'NEXENT_SANDBOX_ENABLED', True) else {'enabled': False}
    if provider != 'kubernetes':
        raise ValueError("Unknown sandbox deployment provider")
    if not settings.NEXENT_SANDBOX_ENABLED:
        return {'provider': provider, 'enabled': False}
    if not settings.IS_DEPLOYED_BY_KUBERNETES:
        raise ValueError("Kubernetes sandbox requires Kubernetes deployment identity")

    from nexent.core.agents.sandbox_contracts import SandboxOwner, SystemSandboxProfile
    from runtime.identity import PROCESS_EPOCH

    owner = SandboxOwner(
        settings.NEXENT_RUNTIME_DEPLOYMENT_ID, settings.NEXENT_RUNTIME_POD_NAMESPACE,
        settings.NEXENT_RUNTIME_POD_NAME, settings.NEXENT_RUNTIME_POD_UID,
        settings.NEXENT_RUNTIME_POD_IP, PROCESS_EPOCH,
    )
    profile = SystemSandboxProfile(
        settings.NEXENT_SANDBOX_DOCKER_IMAGE,
        workspace_volume=settings.NEXENT_SANDBOX_WORKSPACE_CLAIM,
        memory_limit_mb=settings.NEXENT_SANDBOX_MEMORY_LIMIT_MB,
        cpu_quota=settings.NEXENT_SANDBOX_CPU_QUOTA,
        network_disabled=settings.NEXENT_SANDBOX_NETWORK_DISABLED,
        container_workspace_root=settings.NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT or '/mnt/nexent/workdir',
        execution_uid=settings.NEXENT_SANDBOX_EXECUTION_UID,
        execution_gid=settings.NEXENT_SANDBOX_EXECUTION_GID,
    )
    return {'provider': provider, 'owner': owner, 'system_profile': profile}
