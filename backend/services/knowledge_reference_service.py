# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared knowledge-resource guard: references, visibility, statuses, locks.

Deletion cascades: bindings never block a delete. The pieces here let the HTTP
layer, the deletion services, and the reference-writing services share one
implementation:

* ``collect_agent_reference_preview`` lists the (permission-filtered) agents
  bound to a resource, feeding the browser's second confirmation dialog.
* ``knowledge_deletion_guard`` serializes deletion against reference writes.
* ``remove_knowledge_references`` strips a deleted resource out of every
  remaining binding (agent tool instances, skill instances, conversation
  scopes) once the resource is gone.
* ``resolve_item_statuses`` powers the batch status API behind the per-item
  warning markers.
* ``require_available_knowledge_references`` validates newly added bindings.

The service never returns names of agents the caller cannot view.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from consts.const import (
    ASSET_OWNER_TENANT_ID,
    CAN_EDIT_ALL_USER_ROLES,
    PERMISSION_PRIVATE,
)
from consts.error_code import ErrorCode
from consts.exceptions import AppException, ValidationError
from database.client import get_db_session
from database.group_db import query_group_ids_by_user
from database.knowledge_reference_db import (
    acquire_lock_keys,
    query_agent_reference_metadata,
    query_deleted_aidp_kb_ids,
    query_deleted_local_knowledge_ids,
    query_live_agent_reference_rows,
    query_local_knowledge_records,
    query_local_knowledge_records_by_ids,
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

STATUS_AVAILABLE = "available"
STATUS_NOT_FOUND = "not_found"
STATUS_INACCESSIBLE = "inaccessible"
STATUS_LOOKUP_FAILED = "lookup_failed"

REASON_KNOWLEDGE_NOT_FOUND = "KNOWLEDGE_NOT_FOUND"
REASON_KNOWLEDGE_INDEX_NOT_FOUND = "KNOWLEDGE_INDEX_NOT_FOUND"
REASON_PERMISSION_DENIED = "KNOWLEDGE_PERMISSION_DENIED"
REASON_UNAVAILABLE_OR_INACCESSIBLE = "KNOWLEDGE_UNAVAILABLE_OR_INACCESSIBLE"
REASON_UPSTREAM_TIMEOUT = "KNOWLEDGE_UPSTREAM_TIMEOUT"
REASON_CONNECTION_FAILED = "KNOWLEDGE_CONNECTION_FAILED"
REASON_INVALID_RESPONSE = "KNOWLEDGE_INVALID_RESPONSE"

_LOOKUP_FAILED_REASON_CODES = frozenset({
    REASON_UNAVAILABLE_OR_INACCESSIBLE,
    REASON_UPSTREAM_TIMEOUT,
    REASON_CONNECTION_FAILED,
    REASON_INVALID_RESPONSE,
})


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
        metadata = query_agent_reference_metadata(
            session, [row["agent_id"] for row in rows]
        )

    context = build_visibility_context(user_id, tenant_id)
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


def assert_agent_context_visible(
    agent_id: int,
    *,
    user_id: str,
    tenant_id: Optional[str] = None,
) -> None:
    """Enforce view permission before a status query runs in an agent context."""
    with get_db_session() as session:
        metadata = query_agent_reference_metadata(session, [agent_id])
    agent = metadata.get(int(agent_id))
    if not agent:
        raise AppException(
            ErrorCode.COMMON_RESOURCE_NOT_FOUND,
            details={"resource": "agent", "agent_id": int(agent_id)},
        )
    context = build_visibility_context(user_id, tenant_id)
    if not is_agent_visible(context, agent):
        raise AppException(
            ErrorCode.COMMON_FORBIDDEN,
            details={"resource": "agent"},
        )


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


def _resolve_aidp_snapshot(user_id: str, tenant_id: str):
    """Resolve the current AIDP catalog and access set (short-lived cache reused)."""
    from consts.const import AIDP_API_KEY, AIDP_SERVER_URL, AIDP_TENANT_ID
    from ext_components.aidp.services.aidp_access_service import (
        resolve_current_aidp_access,
    )

    return resolve_current_aidp_access(
        server_url=AIDP_SERVER_URL,
        api_key=AIDP_API_KEY,
        user_id=user_id,
        tenant_id=tenant_id,
        aidp_tenant_id=AIDP_TENANT_ID,
    )


def _resolve_local_records(
    session: Any,
    resource_ids: Sequence[str],
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Match local resource ids to their knowledge record.

    Agent tool params persist index names while conversation scopes persist
    numeric knowledge ids; both identify the same knowledge base, so an id that
    is not an index name still resolves through its numeric knowledge id. The
    requested id is always preserved as the response identity.
    """
    requested = dedupe_ids(resource_ids)
    if not requested:
        return {}
    records = query_local_knowledge_records(session, requested)
    numeric_missing = [
        resource_id
        for resource_id in requested
        if resource_id not in records and resource_id.isdigit()
    ]
    if numeric_missing:
        records_by_id = query_local_knowledge_records_by_ids(session, numeric_missing)
        for resource_id in numeric_missing:
            found = records_by_id.get(resource_id)
            if found:
                records[resource_id] = found
    return {resource_id: records.get(resource_id) for resource_id in requested}


def _local_index_name(record: Optional[Dict[str, Any]], resource_id: str) -> str:
    """Return the canonical index name of a resolved record."""
    if not record:
        return resource_id
    return str(record.get("index_name") or resource_id)


def _local_item_status(
    resource_id: str,
    user_id: str,
    tenant_id: Optional[str],
    record: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Resolve one local resource status from database truth and permissions."""
    if record is None:
        return _status_payload(PROVIDER_LOCAL, resource_id, STATUS_NOT_FOUND, REASON_KNOWLEDGE_NOT_FOUND, False)
    from management.services.knowledge_base.permission import (
        resolve_knowledge_base_permission,
    )

    index_name = _local_index_name(record, resource_id)
    try:
        permission = resolve_knowledge_base_permission(index_name, user_id, tenant_id)
    except ValueError:
        return _status_payload(PROVIDER_LOCAL, resource_id, STATUS_NOT_FOUND, REASON_KNOWLEDGE_NOT_FOUND, False)
    except Exception:
        logger.warning(
            "Local knowledge status check failed for %s", index_name, exc_info=True
        )
        return _status_payload(PROVIDER_LOCAL, resource_id, STATUS_LOOKUP_FAILED, REASON_UNAVAILABLE_OR_INACCESSIBLE, True)
    if permission is None:
        return _status_payload(PROVIDER_LOCAL, resource_id, STATUS_INACCESSIBLE, REASON_PERMISSION_DENIED, False)
    return _status_payload(PROVIDER_LOCAL, resource_id, STATUS_AVAILABLE, None, False)


def _status_payload(
    provider: str,
    resource_id: str,
    status: str,
    reason_code: Optional[str],
    retryable: bool,
) -> Dict[str, Any]:
    return {
        "provider": provider,
        "resource_id": resource_id,
        "status": status,
        "reason_code": reason_code,
        "retryable": retryable,
    }


def resolve_local_reference_access(
    index_names: Sequence[str],
    *,
    user_id: str,
    tenant_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Resolve per-id access for local resources without touching the search index.

    Strict by index name on purpose: this resolver feeds the tool-save merge and
    binding validation, where a submitted id is persisted verbatim. Accepting a
    numeric knowledge id here would store an identifier the runtime, the
    reference scan and the deletion lock all fail to match. The read-only status
    API (``resolve_item_statuses``) keeps the numeric-id fallback for
    conversation scopes, which persist knowledge ids.
    """
    names = dedupe_ids(index_names)
    if not names:
        return {}
    with get_db_session() as session:
        records = query_local_knowledge_records(session, names)
    return {
        name: _local_item_status(name, user_id, tenant_id, records.get(name))
        for name in names
    }


def resolve_item_statuses(
    items: Sequence[tuple[str, str]],
    *,
    user_id: str,
    tenant_id: Optional[str] = None,
    vdb_core: Any = None,
) -> List[Dict[str, Any]]:
    """Resolve per-item statuses for the batch status API, preserving input order."""
    unique = list(dict.fromkeys(items))
    statuses: Dict[Tuple[str, str], Dict[str, Any]] = {}

    local_names = [resource_id for provider, resource_id in unique if provider == PROVIDER_LOCAL]
    if local_names:
        with get_db_session() as session:
            records = _resolve_local_records(session, local_names)
        existing_index_names: Optional[Set[str]] = None
        if vdb_core is not None and any(records.values()):
            try:
                existing_index_names = set(vdb_core.get_user_indices("*") or [])
            except Exception:
                logger.warning(
                    "Failed to list search indices for knowledge status check",
                    exc_info=True,
                )
                existing_index_names = None
        for name in local_names:
            record = records.get(name)
            payload = _local_item_status(name, user_id, tenant_id, record)
            index_name = _local_index_name(record, name)
            if (
                payload["status"] == STATUS_AVAILABLE
                and existing_index_names is not None
                and index_name not in existing_index_names
            ):
                payload = _status_payload(
                    PROVIDER_LOCAL, name, STATUS_NOT_FOUND, REASON_KNOWLEDGE_INDEX_NOT_FOUND, True
                )
            statuses[(PROVIDER_LOCAL, name)] = payload

    aidp_ids = [resource_id for provider, resource_id in unique if provider == PROVIDER_AIDP]
    if aidp_ids:
        try:
            snapshot = _resolve_aidp_snapshot(user_id, str(tenant_id or ""))
        except Exception as exc:
            logger.warning("AIDP status lookup failed: %s", exc)
            reason = _classify_upstream_failure(exc)
            for resource_id in aidp_ids:
                statuses[(PROVIDER_AIDP, resource_id)] = _status_payload(
                    PROVIDER_AIDP, resource_id, STATUS_LOOKUP_FAILED, reason, True
                )
        else:
            for resource_id in aidp_ids:
                if resource_id in snapshot.accessible_id_set:
                    payload = _status_payload(PROVIDER_AIDP, resource_id, STATUS_AVAILABLE, None, False)
                elif resource_id in snapshot.remote_ids:
                    payload = _status_payload(
                        PROVIDER_AIDP, resource_id, STATUS_INACCESSIBLE, REASON_PERMISSION_DENIED, False
                    )
                else:
                    payload = _status_payload(
                        PROVIDER_AIDP, resource_id, STATUS_NOT_FOUND, REASON_KNOWLEDGE_NOT_FOUND, False
                    )
                statuses[(PROVIDER_AIDP, resource_id)] = payload

    return [statuses[resource] for resource in unique]


def _classify_upstream_failure(exc: Exception) -> str:
    """Map an upstream failure to a safe reason code without leaking details."""
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return REASON_UPSTREAM_TIMEOUT
    message = str(exc).lower()
    if "timeout" in message or "timed out" in message:
        return REASON_UPSTREAM_TIMEOUT
    if "connection" in name or "connect" in message:
        return REASON_CONNECTION_FAILED
    return REASON_UNAVAILABLE_OR_INACCESSIBLE


def require_available_knowledge_references(
    refs: Sequence[tuple[str, str]],
    *,
    user_id: str,
    tenant_id: Optional[str] = None,
) -> None:
    """Validate newly added bindings against existence and permission rules."""
    local_ids = [resource_id for provider, resource_id in refs if provider == PROVIDER_LOCAL]
    if local_ids:
        access = resolve_local_reference_access(local_ids, user_id=user_id, tenant_id=tenant_id)
        invalid = [
            resource_id
            for resource_id, payload in access.items()
            if payload["status"] != STATUS_AVAILABLE
        ]
        if invalid:
            raise ValidationError(
                "index_names contains a knowledge base the user cannot access: "
                + ", ".join(sorted(invalid))
            )

    aidp_ids = dedupe_ids(resource_id for provider, resource_id in refs if provider == PROVIDER_AIDP)
    if aidp_ids:
        try:
            snapshot = _resolve_aidp_snapshot(user_id, str(tenant_id or ""))
        except Exception as exc:
            raise ValidationError(
                "AIDP is unavailable; the knowledge base configuration was not changed"
            ) from exc
        invalid = [resource_id for resource_id in aidp_ids if resource_id not in snapshot.accessible_id_set]
        if invalid:
            raise ValidationError(
                "kds_list contains a knowledge base the user cannot configure: "
                + ", ".join(sorted(invalid))
            )


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
