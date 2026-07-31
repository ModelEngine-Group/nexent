"""CRUD accessors for ``aidp_kb_permission_t``.

Design contract (see aidp-knowledge-permission-implementation-plan-v7.1 §4.4):
* Every read filters on ``tenant_id`` AND ``delete_flag != 'Y'`` so callers
  cannot accidentally read soft-deleted rows or cross tenant boundaries.
* Writes are explicit per row; ``create_permission`` does not deduplicate and
  relies on the caller having already checked ``get_permission_by_kb_id`` and
  on the partial unique index in PostgreSQL as the final backstop.
* Returned dicts use ISO-formatted timestamps so the service layer can
  serialise them directly to JSON.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, List, Optional, Sequence

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.client import as_dict, get_db_session
from ext_components.aidp.database.db_models import AidpKbPermission

logger = logging.getLogger("aidp_permission_db")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACTIVE_FILTER = "N"


def _active_clause():
    return AidpKbPermission.delete_flag == _ACTIVE_FILTER


def _normalize_group_ids(group_ids: Any) -> list[int]:
    """Return a JSONB-safe list of group IDs.

    ``JSONB`` column accepts lists directly; we still coerce to ``int`` to
    reject malformed payloads early (e.g. ``"1,2,3"`` strings from upstream
    layers that pre-date this table).
    """
    if group_ids is None:
        return []
    if isinstance(group_ids, str):
        return [int(item.strip()) for item in group_ids.split(",") if item.strip()]
    return [int(item) for item in group_ids]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def list_permissions_by_tenant(
    tenant_id: str,
    page: int = 1,
    page_size: int = 20,
    db_session: Optional[Session] = None,
) -> List[dict]:
    """Return active permission records for ``tenant_id`` ordered by
    ``create_time DESC, id DESC`` to keep pagination stable across writes.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")

    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))

    stmt = (
        select(AidpKbPermission)
        .where(and_(_active_clause(), AidpKbPermission.tenant_id == tenant_id))
        .order_by(AidpKbPermission.create_time.desc(), AidpKbPermission.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    with get_db_session(db_session) as session:
        rows = session.execute(stmt).scalars().all()
        return [as_dict(row) for row in rows]


def list_all_permissions_by_tenant(
    tenant_id: str,
    db_session: Optional[Session] = None,
) -> List[dict]:
    """Return ALL active permission records for ``tenant_id`` (no pagination).

    Used by the permission service layer to do application-side permission
    filtering (group intersection / ownership / PRIVATE) before slicing into
    the user-visible page. Without this we would lose items that happen to
    sit in the middle of a DB page that the user cannot see.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")

    stmt = (
        select(AidpKbPermission)
        .where(and_(_active_clause(), AidpKbPermission.tenant_id == tenant_id))
        .order_by(AidpKbPermission.create_time.desc(), AidpKbPermission.id.desc())
    )
    with get_db_session(db_session) as session:
        rows = session.execute(stmt).scalars().all()
        return [as_dict(row) for row in rows]


def count_permissions_by_tenant(
    tenant_id: str,
    db_session: Optional[Session] = None,
) -> int:
    """Return the number of active permission records in a tenant."""
    if not tenant_id:
        raise ValueError("tenant_id is required")
    stmt = (
        select(func.count(AidpKbPermission.id))
        .where(and_(_active_clause(), AidpKbPermission.tenant_id == tenant_id))
    )
    with get_db_session(db_session) as session:
        return int(session.execute(stmt).scalar_one() or 0)


def get_permission_by_kb_id(
    kb_id: str,
    tenant_id: str,
    db_session: Optional[Session] = None,
) -> Optional[dict]:
    """Look up a single active permission row by ``(kb_id, tenant_id)``.

    Returns ``None`` when the KB is unknown, soft-deleted, or belongs to
    another tenant; callers should treat all three cases the same (the row is
    not accessible to the current tenant).
    """
    if not kb_id or not tenant_id:
        raise ValueError("kb_id and tenant_id are required")
    stmt = select(AidpKbPermission).where(
        and_(
            _active_clause(),
            AidpKbPermission.kb_id == kb_id,
            AidpKbPermission.tenant_id == tenant_id,
        )
    )
    with get_db_session(db_session) as session:
        row = session.execute(stmt).scalar_one_or_none()
        return as_dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def create_permission(
    *,
    kb_id: str,
    owner_user_id: str,
    tenant_id: str,
    ingroup_permission: str = "READ_ONLY",
    group_ids: Optional[Iterable[int]] = None,
    resource_status: str = "ACTIVE",
    created_by: Optional[str] = None,
    db_session: Optional[Session] = None,
) -> int:
    """Insert a new permission record and return the new row id.

    Raises ``IntegrityError`` when a duplicate active ``kb_id`` exists; the
    caller is responsible for translating that into HTTP 409.
    """
    if not kb_id or not owner_user_id or not tenant_id:
        raise ValueError("kb_id, owner_user_id and tenant_id are required")
    payload = {
        "kb_id": kb_id,
        "owner_user_id": owner_user_id,
        "tenant_id": tenant_id,
        "ingroup_permission": ingroup_permission,
        "group_ids": _normalize_group_ids(group_ids),
        "resource_status": resource_status,
        "delete_flag": _ACTIVE_FILTER,
    }
    if created_by is not None:
        payload["created_by"] = created_by
        payload["updated_by"] = created_by

    with get_db_session(db_session) as session:
        record = AidpKbPermission(**payload)
        session.add(record)
        try:
            session.flush()
        except IntegrityError as exc:
            logger.warning(
                "AidpKbPermission unique constraint violation kb_id=%s: %s",
                kb_id,
                exc,
            )
            raise
        new_id = record.id
        session.commit()
        return int(new_id)


def update_permission(
    *,
    kb_id: str,
    tenant_id: str,
    ingroup_permission: Optional[str] = None,
    group_ids: Optional[Sequence[int]] = None,
    updated_by: Optional[str] = None,
    db_session: Optional[Session] = None,
) -> bool:
    """Partially update an active permission row.

    Returns ``True`` when a row was modified, ``False`` when no active row
    matched (caller should treat as 404).
    """
    if not kb_id or not tenant_id:
        raise ValueError("kb_id and tenant_id are required")
    values: dict[str, Any] = {}
    if ingroup_permission is not None:
        values["ingroup_permission"] = ingroup_permission
    if group_ids is not None:
        values["group_ids"] = _normalize_group_ids(group_ids)
    if updated_by is not None:
        values["updated_by"] = updated_by
    if not values:
        # Nothing to update — treat as a no-op success so callers can pass
        # idempotent updates without first checking diff state.
        return True

    stmt = (
        update(AidpKbPermission)
        .where(
            and_(
                _active_clause(),
                AidpKbPermission.kb_id == kb_id,
                AidpKbPermission.tenant_id == tenant_id,
            )
        )
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )
    with get_db_session(db_session) as session:
        result = session.execute(stmt)
        session.commit()
        return bool(result.rowcount)


def soft_delete_permission(
    *,
    kb_id: str,
    tenant_id: str,
    updated_by: Optional[str] = None,
    db_session: Optional[Session] = None,
) -> bool:
    """Soft-delete the active row and mark it ``DELETE_PENDING``.

    The active unique index releases the ``kb_id`` once ``delete_flag='Y'`` so
    that the same ``kb_id`` can be re-created later if the tenant re-claims
    it from AIDP.
    """
    if not kb_id or not tenant_id:
        raise ValueError("kb_id and tenant_id are required")
    stmt = (
        update(AidpKbPermission)
        .where(
            and_(
                _active_clause(),
                AidpKbPermission.kb_id == kb_id,
                AidpKbPermission.tenant_id == tenant_id,
            )
        )
        .values(
            delete_flag="Y",
            resource_status="DELETE_PENDING",
            **({"updated_by": updated_by} if updated_by else {}),
        )
        .execution_options(synchronize_session="fetch")
    )
    with get_db_session(db_session) as session:
        result = session.execute(stmt)
        session.commit()
        return bool(result.rowcount)


def update_resource_status(
    *,
    kb_id: str,
    tenant_id: str,
    status: str,
    updated_by: Optional[str] = None,
    db_session: Optional[Session] = None,
) -> bool:
    """Update only ``resource_status`` for an active row."""
    if not kb_id or not tenant_id or not status:
        raise ValueError("kb_id, tenant_id and status are required")
    stmt = (
        update(AidpKbPermission)
        .where(
            and_(
                _active_clause(),
                AidpKbPermission.kb_id == kb_id,
                AidpKbPermission.tenant_id == tenant_id,
            )
        )
        .values(
            resource_status=status,
            **({"updated_by": updated_by} if updated_by else {}),
        )
        .execution_options(synchronize_session="fetch")
    )
    with get_db_session(db_session) as session:
        result = session.execute(stmt)
        session.commit()
        return bool(result.rowcount)


__all__ = [
    "list_permissions_by_tenant",
    "count_permissions_by_tenant",
    "get_permission_by_kb_id",
    "create_permission",
    "update_permission",
    "soft_delete_permission",
    "update_resource_status",
]
