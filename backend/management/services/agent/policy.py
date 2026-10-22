# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent portable tool validation and sandbox configuration policy."""

from copy import deepcopy
from typing import Any, Optional

from contracts.errors.exceptions import AgentToolImportError


def build_sandbox_policy(tenant_id: str, agent_type: str) -> Optional[dict]:
    """
    Assemble a sandbox policy dict from ``NEXENT_SANDBOX_*`` environment variables.

    This is the canonical factory used by the backend service layer to resolve
    ``SandboxConfig`` for every agent run.  It is called before constructing
    ``AgentRunInfo`` so that the resolved config flows into ``NexentAgent``.

    Resolution order:
      1. ``AgentConfig.sandbox_policy`` from the DB (takes precedence).
      2. ``NEXENT_SANDBOX_*`` environment variables (fallback when DB has no policy).

    Args:
        tenant_id: tenant identifier (reserved for future per-tenant overrides).
        agent_type: agent type string (reserved for future per-type overrides).

    Returns:
        A sandbox policy dict, or None when ``NEXENT_SANDBOX_DEFAULT_LEVEL=local``.
    """
    from consts.const import NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS, NEXENT_SANDBOX_CPU_QUOTA, NEXENT_SANDBOX_DEFAULT_LEVEL, NEXENT_SANDBOX_DEFAULT_SCOPE, NEXENT_SANDBOX_DOCKER_IMAGE, NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_S, NEXENT_SANDBOX_MEMORY_LIMIT_MB, NEXENT_SANDBOX_NETWORK_DISABLED, NEXENT_SANDBOX_SHELL_POLICY, NEXENT_SANDBOX_TIMEOUT_S

    level = NEXENT_SANDBOX_DEFAULT_LEVEL
    if level == "local":
        return None

    return {
        "level": level,
        "scope": NEXENT_SANDBOX_DEFAULT_SCOPE,
        "docker_image": NEXENT_SANDBOX_DOCKER_IMAGE,
        "memory_limit_mb": NEXENT_SANDBOX_MEMORY_LIMIT_MB,
        "cpu_quota": NEXENT_SANDBOX_CPU_QUOTA,
        "timeout_seconds": NEXENT_SANDBOX_TIMEOUT_S,
        "host_tool_timeout_seconds": NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_S,
        "network_disabled": NEXENT_SANDBOX_NETWORK_DISABLED,
        "shell_policy": NEXENT_SANDBOX_SHELL_POLICY,
        "auto_sync_outputs": NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS,
    }


def get_sandbox_minio_client() -> Optional[Any]:
    """
    Build and return a MinIO client for sandbox output sync.

    Returns None when MinIO is not configured (safe no-op).

    The caller is responsible for managing the client lifecycle — this function
    returns a fresh client on each call so the caller can call ``close()`` on it
    after the run finishes.
    """
    from consts.const import MINIO_ACCESS_KEY, MINIO_ENDPOINT, MINIO_SECRET_KEY, MINIO_SECURE, NEXENT_SANDBOX_OUTPUT_BUCKET

    if not MINIO_ENDPOINT:
        return None

    try:
        from nexent.storage import MinIOStorageClient
    except ImportError:
        return None

    client = MinIOStorageClient(
        endpoint=MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY or "",
        secret_key=MINIO_SECRET_KEY or "",
        region=None,
        default_bucket=NEXENT_SANDBOX_OUTPUT_BUCKET,
        secure=MINIO_SECURE,
    )
    return client


def portable_tool_params(class_name, params):
    """Copy parameters, dropping only platform-managed AIDP runtime fields."""
    return {
        name: deepcopy(value)
        for name, value in (params or {}).items()
        if class_name != "AidpSearchTool" or name not in AIDP_RUNTIME_PARAMS
    }


def validate_import_tool_params(class_name, source, params, catalog_tool):
    """Validate portable parameters without modifying the repository snapshot."""
    if catalog_tool is None:
        raise AgentToolImportError(f"Cannot find tool {class_name} in {source}.")
    portable = portable_tool_params(class_name, params)
    allowed = {param["name"] for param in catalog_tool.get("params", [])}
    for name in portable:
        if name not in allowed:
            raise AgentToolImportError(
                f"Parameter {name} in tool {class_name} from {source} cannot be found."
            )
    return portable


AIDP_RUNTIME_PARAMS = frozenset(
    {
        "api_key",
        "server_url",
        "tenant_id",
        "observer",
        "allowed_kds_set",
        "kds_name_to_id_map",
    }
)
