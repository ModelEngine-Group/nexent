# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from typing import Any

from contracts.constants.constants import ASSET_OWNER_TENANT_ID, CAN_EDIT_ALL_USER_ROLES, PERMISSION_EDIT
from contracts.errors.exceptions import AgentDraftEditError, AgentNotFoundError, ForbiddenError, ResourceBindingError
from contracts.roles import has_any_role, roles_from_record
from management.db.agent.repository import is_system_agent, query_agent_records_for_nl2agent
from management.db.identity.user_tenant import get_user_role_by_tenant, get_user_tenant_by_user_id
from management.services.permission.asset_owner import resolve_agent_list_permission


def authorize_explicit_agent_sharing(agent: dict, user_id: str, *, manage: bool = False, edit: bool = False) -> None:
    """Enforce explicit sharing at entry points that also handle legacy agents."""
    if agent.get("group_permissions") is None:
        return
    actor = get_user_tenant_by_user_id(user_id) or {}
    role = roles_from_record(actor)
    resource_tenant = agent.get("tenant_id")
    if resource_tenant != actor.get("tenant_id") and (
        resource_tenant != ASSET_OWNER_TENANT_ID or manage or edit
    ):
        raise ForbiddenError("Agent belongs to another tenant")
    can_edit_all = has_any_role(role, CAN_EDIT_ALL_USER_ROLES)
    if manage and not can_edit_all and str(agent.get("created_by")) != str(user_id):
        raise ForbiddenError("Only the owner or an administrator can manage this agent")
    permission = resolve_agent_list_permission(role, agent, user_id, can_edit_all)
    if permission is None or ((manage or edit) and permission != PERMISSION_EDIT):
        raise ForbiddenError("Agent is not accessible for this operation")


def authorize_agent_version_access(agent_id: int, tenant_id: str, user_id: str, *, edit: bool = False) -> None:
    from management.db.agent.repository import search_agent_info_by_agent_id

    try:
        draft = search_agent_info_by_agent_id(agent_id, tenant_id)
    except AgentNotFoundError:
        return
    if isinstance(draft, dict):
        authorize_explicit_agent_sharing(draft, user_id, edit=edit)


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
    if draft.get("group_permissions") is not None and not user_role:
        raise AgentDraftEditError("agent_read_only")
    permission = resolve_agent_list_permission(
        user_role=user_role,
        agent=draft,
        user_id=user_id,
        can_edit_all=has_any_role(user_role, CAN_EDIT_ALL_USER_ROLES),
    )
    if permission != PERMISSION_EDIT:
        raise AgentDraftEditError("agent_read_only")
    return draft


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
