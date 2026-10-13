"""Resolve per-agent sandbox policy without reading deployment environment."""

from typing import Any

from nexent.core.agents.sandbox import SandboxConfig


def resolve_sandbox_config(
    database_policy: dict[str, Any] | None, environment_policy: dict[str, Any] | None, *,
    workspace_mode: str, container_workspace_root: str, failure_policy: str,
) -> SandboxConfig | None:
    """Use a complete DB policy first; omitted policy fields retain SDK defaults.

    Workspace deployment values are defaults that explicit policy fields override.
    Empty DB objects represent an unconfigured policy, not an explicit local level.
    """
    if database_policy is not None and not isinstance(database_policy, dict):
        raise TypeError('Agent sandbox policy must be a dictionary')
    policy = database_policy or environment_policy
    return SandboxConfig.from_dict({
        'workspace_mode': workspace_mode,
        'container_workspace_root': container_workspace_root,
        'failure_policy': failure_policy,
        **policy,
    }) if policy else None
