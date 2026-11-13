# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any

from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES, PERMISSION_EDIT, PERMISSION_PRIVATE
from contracts.errors.exceptions import AgentDraftEditError, AgentNotFoundError, ForbiddenError
from management.db.agent.repository import is_system_agent, query_agent_records_for_nl2agent, search_agent_info_by_agent_id
from management.db.identity.group import query_group_ids_by_user_in_tenant
from management.db.identity.user_tenant import get_user_role_by_tenant
from management.services.permission.asset_owner import resolve_agent_list_permission
from management.services.skill.permission import _to_group_id_set


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


def authorize_debug_version(agent_id: int, version_no: int, user_id: str, tenant_id: str) -> dict:
    """Authorize a tenant draft or published version before exporting any debug resources."""
    agent = search_agent_info_by_agent_id(agent_id, tenant_id, version_no)
    if agent.get("tenant_id") != tenant_id:
        raise AgentNotFoundError("agent not found")

    role = get_user_role_by_tenant(user_id=user_id, tenant_id=tenant_id)
    can_edit_all = (role or "").upper() in CAN_EDIT_ALL_USER_ROLES
    if not can_edit_all and str(agent.get("created_by")) != user_id:
        groups = query_group_ids_by_user_in_tenant(user_id, tenant_id)
        if agent.get("ingroup_permission") == PERMISSION_PRIVATE or not _to_group_id_set(
            agent.get("group_ids")
        ).intersection(groups):
            raise ForbiddenError("Agent is not accessible to the current identity")
    if version_no == 0 and resolve_agent_list_permission(role, agent, user_id, can_edit_all) != PERMISSION_EDIT:
        raise ForbiddenError("You do not have permission to debug this draft")
    return agent


def require_external_relation_edit(local_agent_id: int, tenant_id: str, user_id: str) -> None:
    """Require a tenant-owned, editable ordinary parent before relationship writes."""
    try:
        require_agent_draft_edit(agent_id=local_agent_id, tenant_id=tenant_id, user_id=user_id)
    except AgentDraftEditError as exc:
        if exc.code == "agent_read_only":
            raise ForbiddenError("You do not have permission to edit this agent") from exc
        raise AgentNotFoundError("agent not found") from exc
    if is_system_agent(local_agent_id, tenant_id) is True:
        raise ForbiddenError("System Agent is managed by the platform")
