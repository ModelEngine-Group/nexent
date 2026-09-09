"""Tenant-safe edit authorization for ordinary Agent draft resources."""

from typing import Any

from consts.const import CAN_EDIT_ALL_USER_ROLES, PERMISSION_EDIT
from database.agent_db import query_agent_records_for_nl2agent
from database.user_tenant_db import get_user_role_by_tenant
from .asset_owner_visibility import resolve_agent_list_permission


class AgentDraftEditError(Exception):
    """Stable authorization error shared by draft and resource writes."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ResourceBindingError(Exception):
    """Stable resource validation error used by Tool and Skill writes."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def require_agent_draft_edit(
    *,
    agent_id: int,
    tenant_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Return an editable version-zero Agent record or raise a stable error."""

    records = query_agent_records_for_nl2agent(
        agent_id=agent_id,
        tenant_id=tenant_id,
    )
    if not records:
        raise AgentDraftEditError("agent_not_found")

    draft = next((record for record in records if record.get("version_no") == 0), None)
    if draft is None:
        raise AgentDraftEditError("agent_not_draft")
    if draft.get("delete_flag") == "Y":
        raise AgentDraftEditError("agent_deleted")

    user_role = get_user_role_by_tenant(user_id=user_id, tenant_id=tenant_id)
    permission = resolve_agent_list_permission(
        user_role=user_role,
        agent=draft,
        user_id=user_id,
        can_edit_all=(user_role or "").upper() in CAN_EDIT_ALL_USER_ROLES,
    )
    if permission != PERMISSION_EDIT:
        raise AgentDraftEditError("agent_read_only")
    return draft
