"""ASSET_OWNER tenant visibility filters, feature flags, and response post-processing."""

from typing import Any, Dict, List, Optional

from consts.const import (
    AGENT_PROMPTS_HIDDEN_FLAG,
    ASSET_OWNER_ROLE,
    ASSET_OWNER_TENANT_ID,
    ENABLE_ASSET_OWNER_ROLE,
    PERMISSION_EDIT,
    PERMISSION_READ,
)
from consts.exceptions import ValidationError


_PROMPT_FIELDS = ("duty_prompt", "constraint_prompt", "few_shots_prompt")


ASSET_OWNER_RESOURCES_ROUTE = "/asset-owner-resources"


def is_asset_owner_enabled() -> bool:
    """Return whether the ASSET_OWNER feature flag is enabled."""
    return ENABLE_ASSET_OWNER_ROLE


def require_asset_owner_enabled() -> None:
    """Raise ValidationError when the ASSET_OWNER feature is disabled."""
    if not ENABLE_ASSET_OWNER_ROLE:
        raise ValidationError("ASSET_OWNER feature is not enabled")


def filter_accessible_routes_for_asset_owner_feature(
    accessible_routes: List[str],
) -> List[str]:
    """Remove asset-owner nav route when the ASSET_OWNER feature flag is disabled."""
    if ENABLE_ASSET_OWNER_ROLE:
        return accessible_routes
    return [r for r in accessible_routes if r != ASSET_OWNER_RESOURCES_ROUTE]


def can_view_skill(caller_tenant_id: Optional[str], skill_tenant_id: Optional[str]) -> bool:
    """
    Return True when the caller may view a skill and its files.

    ASSET_OWNER-scoped skills (tenant_id asset_owner_tenant_id or legacy "") are
    visible only to callers in the ASSET_OWNER virtual tenant.
    """

    if skill_tenant_id == ASSET_OWNER_TENANT_ID:
        return caller_tenant_id == ASSET_OWNER_TENANT_ID
    return True


def resolve_agent_list_permission(
    user_role: str,
    agent: Dict[str, Any],
    user_id: str,
    can_edit_all: bool,
) -> str:
    """
    Resolve list-item permission for an agent.

    Highest priority: ASSET_OWNER-scoped agents are READ_ONLY for callers whose
    user_role is not ASSET_OWNER (overrides can_edit_all, creator, ingroup_permission).
    """
    role = (user_role or "").upper()
    if agent.get("tenant_id") == ASSET_OWNER_TENANT_ID and role != ASSET_OWNER_ROLE:
        return PERMISSION_READ
    if can_edit_all or str(agent.get("created_by")) == str(user_id):
        return PERMISSION_EDIT
    ingroup_permission = agent.get("ingroup_permission")
    return ingroup_permission if ingroup_permission is not None else PERMISSION_READ


def apply_agent_detail_prompt_visibility(
    caller_tenant_id: Optional[str],
    agent_info: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Mask system prompt fields when a non-ASSET_OWNER caller views an ASSET_OWNER-scoped agent.

    Sets duty_prompt, constraint_prompt, and few_shots_prompt to None and adds
    prompts_hidden=True so clients can render a permission-denied state.
    """
    result = dict(agent_info)
    if caller_tenant_id == ASSET_OWNER_TENANT_ID:
        return result
    if result.get("tenant_id") != ASSET_OWNER_TENANT_ID:
        return result
    for field in _PROMPT_FIELDS:
        result[field] = None
    result[AGENT_PROMPTS_HIDDEN_FLAG] = True
    return result


def postprocess_knowledge_visibility(
    items: List[Dict[str, Any]],
    caller_role: Optional[str],
    caller_tenant_id: Optional[str],
) -> List[Dict[str, Any]]:
    """Return knowledge records after visibility post-processing (no-op for now)."""
    _ = (caller_role, caller_tenant_id)
    return items
