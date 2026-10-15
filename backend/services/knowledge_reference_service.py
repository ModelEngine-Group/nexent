# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared knowledge binding previews, cascade cleanup and write guards."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from consts.const import (
    ASSET_OWNER_TENANT_ID,
    CAN_EDIT_ALL_USER_ROLES,
    PERMISSION_PRIVATE,
)
from consts.exceptions import ValidationError
from database.client import get_db_session
from database.group_db import query_group_ids_by_user
from database.knowledge_reference_db import (
    acquire_lock_keys,
    query_agent_reference_metadata,
    query_deleted_aidp_kb_ids,
    query_deleted_local_knowledge_ids,
    query_live_agent_reference_rows,
    query_local_knowledge_records,
    strip_deleted_resource_from_bindings,
)
from database.user_tenant_db import get_user_tenant_by_user_id
from utils.knowledge_reference import (
    PROVIDER_AIDP,
    PROVIDER_LOCAL,
    dedupe_ids,
    resource_lock_key,
)


logger = logging.getLogger("knowledge_reference_service")

@dataclass
class VisibilityContext:
    """Caller identity used by the agent list visibility rule."""

    user_id: str
    tenant_id: str
    user_role: str
    can_edit_all: bool
    user_group_ids: Set[int] = field(default_factory=set)


def build_visibility_context(user_id: str, tenant_id: Optional[str] = None) -> VisibilityContext:
    """Resolve the caller's role and groups once per request."""
    record = get_user_tenant_by_user_id(user_id) or {}
    role = str(record.get("user_role") or "").upper()
    can_edit_all = role in CAN_EDIT_ALL_USER_ROLES
    user_group_ids: Set[int] = set()
    if not can_edit_all:
        try:
            user_group_ids = {int(item) for item in (query_group_ids_by_user(user_id) or [])}
        except Exception:
            logger.warning("Failed to query user group ids for visibility filtering", exc_info=True)
            user_group_ids = set()
    return VisibilityContext(
        user_id=str(user_id),
        tenant_id=str(tenant_id or record.get("tenant_id") or ""),
        user_role=role,
        can_edit_all=can_edit_all,
        user_group_ids=user_group_ids,
    )


def is_agent_visible(context: VisibilityContext, agent: Dict[str, Any]) -> bool:
    """Mirror the agent list visibility rule without its enabled filter.

    A disabled agent still owns its persisted configuration, so it stays
    visible in the deletion preview instead of being treated as permission-hidden.
    """
    if context.can_edit_all:
        return True
    if str(agent.get("created_by")) == str(context.user_id):
        return True
    if agent.get("tenant_id") == ASSET_OWNER_TENANT_ID:
        # ASSET_OWNER-scoped agents are listed read-only for other roles.
        return True
    from utils.str_utils import convert_string_to_list

    agent_group_ids = set(convert_string_to_list(agent.get("group_ids")))
    if not context.user_group_ids.intersection(agent_group_ids):
        return False
    return agent.get("ingroup_permission") != PERMISSION_PRIVATE


def collect_agent_reference_preview(
    resources: Sequence[tuple[str, str]],
    *,
    user_id: str,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the permission-filtered agent list bound to the resources.

    Deletion cascades, so this only feeds the second confirmation dialog: one
    row per agent (draft and every published version collapse into the single
    agent name), with hidden references reported as an aggregate count.
    """
    with get_db_session() as session:
        rows = query_live_agent_reference_rows(session, resources)
        if not rows:
            return {
                "agents": [],
                "hidden_agent_count": 0,
                "total_agent_count": 0,
            }
        context = build_visibility_context(user_id, tenant_id)
        metadata = query_agent_reference_metadata(
            session, [row["agent_id"] for row in rows], tenant_id=context.tenant_id
        )
    aggregated: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        agent_id = int(row["agent_id"])
        agent = metadata.get(agent_id)
        if not agent:
            continue
        aggregated.setdefault(agent_id, agent)

    visible_agents: List[Dict[str, Any]] = []
    hidden_agent_count = 0
    for agent_id, agent in aggregated.items():
        if not is_agent_visible(context, agent):
            hidden_agent_count += 1
            continue
        visible_agents.append(
            {
                "agent_id": agent_id,
                "display_name": agent.get("display_name")
                or agent.get("name")
                or str(agent_id),
            }
        )

    visible_agents.sort(key=lambda item: (str(item["display_name"]), item["agent_id"]))
    return {
        "agents": visible_agents,
        "hidden_agent_count": hidden_agent_count,
        "total_agent_count": len(aggregated),
    }


def remove_knowledge_references(resources: Sequence[tuple[str, str]]) -> Dict[str, int]:
    """Strip deleted resources out of every binding that still lists them.

    Deletion cascades, so this runs once the resource is actually gone: agent
    tool instances (draft and published versions), skill instances, and
    conversation knowledge scopes all stop referencing it.
    """
    with get_db_session() as session:
        counts = strip_deleted_resource_from_bindings(session, resources)
    if any(counts.values()):
        logger.info(
            "Deleted resources cleaned from bindings %s -> %s",
            resources,
            counts,
        )
    return counts


def lock_namespace_for(provider: str) -> str:
    """Return the deployment namespace used in the resource lock key."""
    if provider == PROVIDER_AIDP:
        # AIDP deployment configuration is read lazily: non-AIDP deployments
        # do not need these constants to import the shared service.
        from consts.const import AIDP_SERVER_URL, AIDP_TENANT_ID

        server = str(AIDP_SERVER_URL or "").strip().rstrip("/").lower()
        return f"aidp:{server}:{AIDP_TENANT_ID}"
    return ""


def resource_lock_keys_for(refs: Iterable[tuple[str, str]]) -> List[int]:
    """Compute lock keys for a mixed set of resources."""
    return [
        resource_lock_key(provider, resource_id, lock_namespace_for(provider))
        for provider, resource_id in refs
    ]


@contextmanager
def knowledge_deletion_guard(resources: Sequence[tuple[str, str]]):
    """Exclude reference writes while the deletion cascades over the resource.

    A binding arriving after the deletion cannot succeed because the resource
    no longer passes existence validation, and the lock closes the window
    where one could commit between the cascade cleanup and the deletion.
    """
    with acquire_lock_keys(resource_lock_keys_for(resources)):
        yield


@contextmanager
def knowledge_reference_write_guard(refs: Sequence[tuple[str, str]]):
    """Serialize a reference write against concurrent deletion of the same resources."""
    with acquire_lock_keys(resource_lock_keys_for(refs)):
        yield


def get_accessible_local_indices(
    index_names: Sequence[str],
    *,
    user_id: str,
    tenant_id: Optional[str] = None,
) -> Set[str]:
    """Return accessible canonical index names for the tool-save merge.

    Strict by index name on purpose: this resolver feeds the tool-save merge and
    binding validation, where a submitted id is persisted verbatim. Accepting a
    numeric knowledge id here would store an identifier the runtime, the
    reference scan and the deletion lock all fail to match.
    """
    from management.services.knowledge_base.permission import resolve_knowledge_base_permission

    names = dedupe_ids(index_names)
    if not names:
        return set()
    with get_db_session() as session:
        records = query_local_knowledge_records(session, names)
    accessible = set()
    for name in names:
        if name not in records:
            continue
        try:
            permission = resolve_knowledge_base_permission(name, user_id, tenant_id)
        except ValueError:
            continue
        if permission is not None:
            accessible.add(name)
    return accessible


def reject_confirmed_deleted_knowledge_references(
    refs: Sequence[tuple[str, str]],
    *,
    tenant_id: Optional[str] = None,
) -> None:
    """Reject writes that re-bind a resource already deleted in this deployment.

    Cross-environment imports legitimately reference unknown ids, so only ids
    with explicit local deletion evidence (soft-deleted record or permission
    row) are refused. This closes the race where a deletion completed after the
    importing client started but before its reference write committed.
    """
    local_ids = [resource_id for provider, resource_id in refs if provider == PROVIDER_LOCAL]
    aidp_ids = dedupe_ids(resource_id for provider, resource_id in refs if provider == PROVIDER_AIDP)
    confirmed: Set[str] = set()
    if local_ids or aidp_ids:
        with get_db_session() as session:
            if local_ids:
                confirmed.update(query_deleted_local_knowledge_ids(session, local_ids))
            if aidp_ids:
                confirmed.update(
                    query_deleted_aidp_kb_ids(session, aidp_ids, tenant_id)
                )
    if confirmed:
        raise ValidationError(
            "References target knowledge bases that were deleted: "
            + ", ".join(sorted(confirmed))
        )
