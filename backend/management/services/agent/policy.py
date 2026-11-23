# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent portable tool validation and sandbox configuration policy."""

from copy import deepcopy

from contracts.errors.exceptions import AgentToolImportError
from infrastructure.sandbox_deployment import (
    default_sandbox_policy,
    get_sandbox_minio_client as get_sandbox_minio_client,
)
from nexent.core.ext_components.aidp.constants import AIDP_SEARCH_TOOL_CLASSES
from nexent.core.ext_components.aidp.retrieval_config import prepare_config


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


def prepare_import_retrieval_params(agent_info):
    """Prepare user-uploaded policies before creating any agents or skills."""
    for agent in agent_info.agent_info.values():
        for tool in agent.tools:
            if tool.class_name in AIDP_SEARCH_TOOL_CLASSES:
                try:
                    portable = portable_tool_params(tool.class_name, tool.params)
                    tool.params = {**portable, **prepare_config(portable, {})}
                except ValueError as exc:
                    raise AgentToolImportError(str(exc)) from exc
