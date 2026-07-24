"""Permission resolution and runtime whitelist helpers for AIDP KBs (v7.1).

This module composes three inputs to decide whether a user may act on a
given AIDP knowledge base:

1. ``aidp_kb_permission_t`` (the active ``kb_id -> group_ids`` mapping).
2. The user's role within the tenant (``user_tenant_t.user_role``).
3. The user's group memberships within the tenant (a join through
   ``tenant_group_info_t`` so we never leak cross-tenant group IDs).

Decision order:
    1. Management roles (SU/ADMIN/SPEED) -> EDIT (within tenant boundary).
    2. ASSET_OWNER -> EDIT only inside its asset context; we conservatively
       grant EDIT here so the rest of the system can rely on a single rule.
       Callers that need finer ASSET_OWNER scoping can override at the
       resource layer.
    3. Creator (matches ``owner_user_id``) -> EDIT.
    4. ``PRIVATE`` -> no access (except creator).
    5. Empty ``group_ids`` -> no access (except creator/management).
    6. Group intersection exists -> ``ingroup_permission``; otherwise no access.

Errors raised here map to HTTP status codes in ``aidp_mgmt_app``:
* ``AidpKbNotFoundError`` -> 404
* ``AidpKbPermissionDeniedError`` -> 403
* ``AidpKbConflictError`` -> 409
* ``AidpGroupValidationError`` -> 400
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from consts.const import CAN_EDIT_ALL_USER_ROLES
from database import group_db as group_db_module
from database.group_db import (
    filter_tenant_group_ids,
    query_group_ids_by_user_in_tenant,
)
from database import user_tenant_db as user_tenant_db_module
from database.user_tenant_db import get_user_role_by_tenant
from ext_components.aidp.consts.aidp_exceptions import (
    AidpGroupValidationError,
    AidpKbConflictError,
    AidpKbNotFoundError,
    AidpKbPermissionDeniedError,
)
from ext_components.aidp.database import aidp_permission_db

logger = logging.getLogger("aidp_permission_service")


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

# Permission levels used internally; mirrors the v7.1 matrix.
EDIT = "EDIT"
READ_ONLY = "READ_ONLY"
PRIVATE = "PRIVATE"
CREATOR = "CREATOR"

# Argument values for require_permission().
REQUIRE_READ = "READ"
REQUIRE_EDIT = "EDIT"

# Ordered rank for permission comparison.
_RANK = {REQUIRE_READ: 1, REQUIRE_EDIT: 2}


@dataclass(frozen=True)
class AidpPermissionDecision:
    """Immutable result of a permission evaluation.

    Attributes:
        kb_id: Target kds_id.
        tenant_id: Tenant the row belongs to.
        user_id: Caller.
        permission: Effective permission ("EDIT" / "READ_ONLY" / "CREATOR" /
            None when the user has no access).
        is_management_role: True when the decision was made via
            ``CAN_EDIT_ALL_USER_ROLES``.
        matched_group_ids: Group IDs that matched the user's memberships.
            Empty tuple when access came from creator or management role.
    """

    kb_id: str
    tenant_id: str
    user_id: str
    permission: str | None
    is_management_role: bool
    matched_group_ids: tuple[int, ...]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_group_ids(raw: Any) -> list[int]:
    """Normalise ``group_ids`` from JSONB or comma-separated text into ints."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        return [int(item.strip()) for item in raw.split(",") if item.strip()]
    if isinstance(raw, Iterable):
        return [int(item) for item in raw]
    raise ValueError(f"Unsupported group_ids payload: {type(raw).__name__}")


def _validate_group_ids_strict(
    group_ids: Sequence[int], tenant_id: str
) -> list[int]:
    """Reject any ``group_ids`` that are not part of ``tenant_id``.

    Differs from :func:`filter_tenant_group_ids` in that it raises an error
    for the first mismatch instead of silently dropping invalid IDs.
    """
    if not group_ids:
        return []
    valid = set(group_db_module.filter_tenant_group_ids(list(group_ids), tenant_id))
    invalid = [int(g) for g in group_ids if int(g) not in valid]
    if invalid:
        raise AidpGroupValidationError(invalid_ids=invalid, tenant_id=tenant_id)
    return [int(g) for g in group_ids]


def _get_user_role(user_id: str, tenant_id: str) -> str:
    return user_tenant_db_module.get_user_role_by_tenant(user_id, tenant_id)


def _get_user_groups(user_id: str, tenant_id: str) -> list[int]:
    return group_db_module.query_group_ids_by_user_in_tenant(user_id, tenant_id)


def _resolve_permission(
    record: dict,
    user_id: str,
    tenant_id: str,
    user_groups: Sequence[int] | None = None,
) -> AidpPermissionDecision:
    """Compute effective permission using the matrix described in the module docstring.

    ``record`` is a row from ``aidp_kb_permission_t`` keyed by ``kb_id`` +
    ``tenant_id``. ``user_groups`` may be supplied to avoid an extra DB round
    trip when callers already have them in scope.
    """
    if not record:
        # Treat as 404 so callers can map this consistently.
        raise AidpKbNotFoundError(kb_id="", tenant_id=tenant_id)

    kb_id = record["kb_id"]
    owner_user_id = record.get("owner_user_id")
    ingroup_permission = record.get("ingroup_permission") or READ_ONLY
    record_groups = set(_parse_group_ids(record.get("group_ids")))

    role = _get_user_role(user_id, tenant_id)
    is_management = role in CAN_EDIT_ALL_USER_ROLES
    if is_management:
        return AidpPermissionDecision(
            kb_id=kb_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission=EDIT,
            is_management_role=True,
            matched_group_ids=tuple(),
        )

    if owner_user_id and owner_user_id == user_id:
        return AidpPermissionDecision(
            kb_id=kb_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission=EDIT,
            is_management_role=False,
            matched_group_ids=tuple(),
        )

    if ingroup_permission == PRIVATE:
        return AidpPermissionDecision(
            kb_id=kb_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission=None,
            is_management_role=False,
            matched_group_ids=tuple(),
        )

    if not record_groups:
        return AidpPermissionDecision(
            kb_id=kb_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission=None,
            is_management_role=False,
            matched_group_ids=tuple(),
        )

    user_group_set = (
        set(int(g) for g in user_groups)
        if user_groups is not None
        else set(_get_user_groups(user_id, tenant_id))
    )
    matched = sorted(record_groups & user_group_set)
    if not matched:
        return AidpPermissionDecision(
            kb_id=kb_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission=None,
            is_management_role=False,
            matched_group_ids=tuple(),
        )

    return AidpPermissionDecision(
        kb_id=kb_id,
        tenant_id=tenant_id,
        user_id=user_id,
        permission=ingroup_permission,
        is_management_role=False,
        matched_group_ids=tuple(matched),
    )


def _decision_meets(decision: AidpPermissionDecision, required: str) -> bool:
    """Return True when ``decision.permission`` satisfies the required level."""
    if decision.permission is None:
        return False
    if required == REQUIRE_READ:
        return decision.permission in (READ_ONLY, EDIT, CREATOR)
    if required == REQUIRE_EDIT:
        return decision.permission in (EDIT, CREATOR)
    raise ValueError(f"Unsupported required permission: {required!r}")


# ---------------------------------------------------------------------------
# DB operation wrappers
# ---------------------------------------------------------------------------


def create_permission(*args: Any, **kwargs: Any) -> int:
    return aidp_permission_db.create_permission(*args, **kwargs)


def update_permission(*args: Any, **kwargs: Any) -> bool:
    return aidp_permission_db.update_permission(*args, **kwargs)


def soft_delete_permission(*args: Any, **kwargs: Any) -> bool:
    return aidp_permission_db.soft_delete_permission(*args, **kwargs)


def update_resource_status(*args: Any, **kwargs: Any) -> bool:
    return aidp_permission_db.update_resource_status(*args, **kwargs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _compute_accessible_rows(user_id: str, tenant_id: str) -> list[dict]:
    """Return KB rows where the user has non-null permission.

    Pulls ALL active rows for the tenant, applies the permission matrix
    (management / owner / PRIVATE / group intersection), and keeps only
    the rows the user can see. Used by both :func:`get_accessible_kbs`
    and :func:`count_accessible_kbs` so the page slice and the count
    never disagree on what is visible.
    """
    rows = aidp_permission_db.list_all_permissions_by_tenant(tenant_id=tenant_id)
    user_groups = _get_user_groups(user_id, tenant_id)
    role = _get_user_role(user_id, tenant_id)
    is_management = role in CAN_EDIT_ALL_USER_ROLES

    accessible: list[dict] = []
    for row in rows:
        if is_management or row.get("owner_user_id") == user_id:
            new_row = dict(row)
            new_row["permission"] = EDIT
            accessible.append(new_row)
            continue
        decision = _resolve_permission(row, user_id, tenant_id, user_groups)
        # Drop rows the user cannot see: PRIVATE, not-in-group, or empty
        # group_ids all produce ``permission is None`` here.
        if decision.permission is None:
            continue
        new_row = dict(row)
        new_row["permission"] = decision.permission
        accessible.append(new_row)
    return accessible


def get_accessible_kbs(
    user_id: str,
    tenant_id: str,
    page: int = 1,
    page_size: int = 10,
) -> list[dict]:
    """Return KBs the user can access, filtered AND paginated.

    Each row carries the effective ``permission`` string (``EDIT`` /
    ``READ_ONLY`` / ``CREATOR``) computed via :func:`_resolve_permission`.
    Rows the user cannot see (PRIVATE / not-in-group / creator-only) are
    filtered out before slicing into the requested page, so the caller
    receives at most ``page_size`` rows and the visible items are always
    what the user is allowed to read.
    """
    accessible = _compute_accessible_rows(user_id, tenant_id)
    page = max(1, int(page))
    page_size = max(1, int(page_size))
    start = (page - 1) * page_size
    end = start + page_size
    return accessible[start:end]


def count_accessible_kbs(user_id: str, tenant_id: str) -> int:
    """Count KBs the user can actually access.

    The previous implementation returned the tenant KB total and let the
    page-level filter drop invisible rows, which broke pagination totals
    when the user lacked access to many KBs in the tenant. Now the count
    reflects the post-filter accessible set so ``has_more`` / ``total``
    on the frontend matches reality.
    """
    accessible = _compute_accessible_rows(user_id, tenant_id)
    return len(accessible)


def filter_accessible_kds(
    kds_ids: Sequence[str],
    user_id: str,
    tenant_id: str,
) -> list[str]:
    """Preserve ``kds_ids`` order while dropping IDs the user cannot read."""
    if not kds_ids:
        return []
    user_groups = _get_user_groups(user_id, tenant_id)
    role = _get_user_role(user_id, tenant_id)
    is_management = role in CAN_EDIT_ALL_USER_ROLES

    allowed: list[str] = []
    for kds_id in kds_ids:
        record = _get_permission_record(kb_id=kds_id, tenant_id=tenant_id)
        if record is None:
            continue
        if is_management or record.get("owner_user_id") == user_id:
            allowed.append(kds_id)
            continue
        decision = _resolve_permission(record, user_id, tenant_id, user_groups)
        if _decision_meets(decision, REQUIRE_READ):
            allowed.append(kds_id)
    return allowed


def get_allowed_kds_list(user_id: str, tenant_id: str) -> list[str]:
    """Build the runtime whitelist used by ``AidpSearchTool``.

    Returns the subset of ``kb_ids`` in the tenant where the user has at least
    ``READ`` access. The list is recomputed every agent run so permission
    changes take effect immediately (no cache).
    """
    rows = aidp_permission_db.list_permissions_by_tenant(
        tenant_id=tenant_id, page=1, page_size=200
    )
    user_groups = _get_user_groups(user_id, tenant_id)
    role = _get_user_role(user_id, tenant_id)
    is_management = role in CAN_EDIT_ALL_USER_ROLES

    allowed: list[str] = []
    for row in rows:
        if is_management or row.get("owner_user_id") == user_id:
            allowed.append(row["kb_id"])
            continue
        decision = _resolve_permission(row, user_id, tenant_id, user_groups)
        if _decision_meets(decision, REQUIRE_READ):
            allowed.append(row["kb_id"])
    return allowed


def require_permission(
    kb_id: str,
    user_id: str,
    tenant_id: str,
    required: str,
) -> AidpPermissionDecision:
    """Assert that ``user_id`` has at least ``required`` access on ``kb_id``.

    Raises:
        AidpKbNotFoundError: When no active row matches ``(kb_id, tenant_id)``.
        AidpKbPermissionDeniedError: When the row exists but the user lacks
            the required permission.
    """
    if required not in _RANK:
        raise ValueError(f"Unsupported required permission: {required!r}")

    record = _get_permission_record(kb_id=kb_id, tenant_id=tenant_id)
    if record is None:
        raise AidpKbNotFoundError(kb_id=kb_id, tenant_id=tenant_id)

    decision = _resolve_permission(record, user_id, tenant_id)
    if not _decision_meets(decision, required):
        logger.info(
            "Aidp permission denied: user=%s tenant=%s kb=%s required=%s have=%s",
            user_id, tenant_id, kb_id, required, decision.permission,
        )
        raise AidpKbPermissionDeniedError(
            kb_id=kb_id, user_id=user_id, required=required,
        )
    return decision


__all__ = [
    "AidpPermissionDecision",
    "READ_ONLY",
    "EDIT",
    "PRIVATE",
    "CREATOR",
    "REQUIRE_READ",
    "REQUIRE_EDIT",
    "AidpKbNotFoundError",
    "AidpKbPermissionDeniedError",
    "AidpKbConflictError",
    "AidpGroupValidationError",
    "create_permission",
    "update_permission",
    "soft_delete_permission",
    "update_resource_status",
    "filter_accessible_kds",
    "get_accessible_kbs",
    "count_accessible_kbs",
    "get_allowed_kds_list",
    "require_permission",
]


def _get_permission_record(
    *, kb_id: str, tenant_id: str
) -> dict | None:
    """Look up the active permission row for ``(kb_id, tenant_id)``.

    This indirection exists so unit tests can patch the permission service
    without depending on the ``aidp_permission_db`` module reference held
    at import time (which may be replaced by other conftests).
    """
    return aidp_permission_db.get_permission_by_kb_id(
        kb_id=kb_id, tenant_id=tenant_id
    )
