"""ORM models for the AIDP knowledge base permission subsystem (v7.1).

These models back the ``aidp_kb_permission_t`` table introduced in
``deploy/sql/migrations/v2.4.0_0723_add_aidp_kb_permission.sql``. The schema
is intentionally separate from the SDK ``aidp_client`` so the SDK can stay a
pure HTTP adapter while permission decisions live in the backend.

The model inherits ``TableBase`` so it shares the audit columns and
``delete_flag`` semantics with the rest of the backend ORM. To keep the
AIDP ORM self-contained for tests, we declare the audit columns inline
instead of mixing with the global ``TableBase.metadata`` registry.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Index,
    Integer,
    String,
    TIMESTAMP,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base

from database.db_models import SCHEMA


# Dedicated Declarative base so the AIDP metadata can be re-declared in
# tests without colliding with the shared TableBase.metadata.
AidpKbPermissionBase = declarative_base()


class AidpKbPermission(AidpKbPermissionBase):
    """ORM model for ``nexent.aidp_kb_permission_t``.

    A single row represents a KB that Nexent has observed via AIDP and
    decided to manage. The active uniqueness on ``kb_id`` is enforced in
    PostgreSQL (see migration), so application code MUST treat
    ``create_permission`` as non-idempotent and let ``get_permission_by_kb_id``
    act as the first concurrency check before insertion.
    """

    __tablename__ = "aidp_kb_permission_t"
    __table_args__ = (
        Index(
            "ix_aidp_kb_permission_tenant_active",
            "tenant_id",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        {"schema": SCHEMA},
    )

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
        doc="Primary key, auto-increment",
    )
    kb_id = Column(String(128), nullable=False, doc="AIDP kds_id")
    owner_user_id = Column(
        String(100),
        nullable=False,
        doc="Nexent user_id of the KB creator",
    )
    tenant_id = Column(String(100), nullable=False, doc="Nexent tenant_id")
    ingroup_permission = Column(
        String(30),
        nullable=False,
        default="READ_ONLY",
        doc="EDIT / READ_ONLY / PRIVATE",
    )
    group_ids = Column(
        JSONB,
        nullable=False,
        default=list,
        doc="JSON array of group IDs, e.g. [1, 2, 3]",
    )
    resource_status = Column(
        String(30),
        nullable=False,
        default="ACTIVE",
        doc="CREATING / ACTIVE / DELETE_PENDING / ORPHANED / UNAVAILABLE",
    )
    create_time = Column(
        TIMESTAMP(timezone=False),
        server_default=func.now(),
        doc="Creation time",
    )
    update_time = Column(
        TIMESTAMP(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        doc="Update time",
    )
    created_by = Column(String(100), doc="Creator")
    updated_by = Column(String(100), doc="Updater")
    delete_flag = Column(
        String(1),
        default="N",
        doc="Soft delete flag. Active rows are N; soft delete sets Y.",
    )
