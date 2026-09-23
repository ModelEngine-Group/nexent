"""Resolve authenticated caller identity for tool-side authorization."""

import logging
from typing import Any

from consts.const import TENANT_NAME
from nexent.core.agents.agent_model import AgentConfig

logger = logging.getLogger(__name__)


def agent_tree_needs_user_context(agent_config: AgentConfig) -> bool:
    """Return whether an agent tree can forward caller identity externally."""
    if not all(hasattr(agent_config, field) for field in ("tools", "external_a2a_agents", "managed_agents")):
        return False
    return (
        any(tool.source == "mcp" for tool in agent_config.tools)
        or bool(agent_config.external_a2a_agents)
        or any(
            agent_tree_needs_user_context(sub_agent)
            for sub_agent in agent_config.managed_agents
        )
    )


def build_tool_user_context(user_id: str, tenant_id: str) -> dict[str, Any]:
    """Build a tenant-scoped identity snapshot without blocking a run on lookup errors."""
    from database.group_db import query_groups_by_user
    from database.tenant_config_db import get_single_config_info
    from database.user_tenant_db import get_user_tenant_in_tenant

    user_context: dict[str, Any] = {
        "tenant_id": str(tenant_id or ""),
        "tenant_name": "",
        "user_id": str(user_id or ""),
        "user_name": "",
        "user_account": "",
        "user_groups": [],
    }

    try:
        tenant_record = get_single_config_info(tenant_id, TENANT_NAME)
        user_context["tenant_name"] = str((tenant_record or {}).get("config_value") or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool user context: tenant name lookup failed: %s", exc)

    try:
        user_record = get_user_tenant_in_tenant(user_id, tenant_id)
        user_email = str((user_record or {}).get("user_email") or "")
        user_context["user_name"] = user_email
        user_context["user_account"] = user_email
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool user context: user email lookup failed: %s", exc)

    try:
        current_tenant_id = str(tenant_id or "")
        user_context["user_groups"] = [
            str(group["group_name"])
            for group in query_groups_by_user(user_id) or []
            if group.get("group_name")
            and str(group.get("tenant_id") or "") == current_tenant_id
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool user context: user groups lookup failed: %s", exc)

    return user_context


def resolve_tool_user_context(
    agent_config: AgentConfig,
    user_id: str,
    tenant_id: str,
) -> dict[str, Any] | None:
    """Resolve caller identity only when an MCP or external A2A path can use it."""
    if not agent_tree_needs_user_context(agent_config):
        return None
    return build_tool_user_context(user_id, tenant_id)
