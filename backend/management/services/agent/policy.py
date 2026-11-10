# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent portable tool validation and sandbox configuration policy."""

from copy import deepcopy

from contracts.errors.exceptions import AgentToolImportError
from infrastructure.sandbox_deployment import (
    default_sandbox_policy,
    get_sandbox_minio_client as get_sandbox_minio_client,
)


def build_sandbox_policy(tenant_id: str, agent_type: str) -> dict | None:
    """Preserve the compatibility helper for in-process callers."""
    return default_sandbox_policy()


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
