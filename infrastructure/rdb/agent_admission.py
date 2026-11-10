# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Durable AgentOS submission claims, scoped by the signed actor."""

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import Boolean, Column, Integer, String, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from infrastructure.rdb.base import SCHEMA, TableBase
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_state import tenant_membership_matches


class ConversationRunAdmission(TableBase):
    __tablename__ = "conversation_run_admission_t"
    __table_args__ = {"schema": SCHEMA}

    scope_sha256 = Column(String(64), primary_key=True, doc="Digest of the actor scope and idempotency key.")
    tenant_id = Column(String(100), nullable=False, doc="Tenant that owns this submission.")
    run_id = Column(String(32), nullable=False, doc="Server-assigned run identifier.")
    request_sha256 = Column(String(64), nullable=False, doc="Digest of the normalized submitted request.")
    status = Column(String(30), nullable=False, server_default=text("'pending'"), doc="Admission outcome.")
    conversation_id = Column(Integer, doc="Conversation bound to the admitted run.")
    journal_available = Column(Boolean, nullable=False, server_default=text("false"), doc="Run output journal opened.")


class AdmissionScopeError(ValueError):
    """The signed actor cannot access this claim."""


class AdmissionRequestConflict(ValueError):
    """The actor reused a key with another request."""


@dataclass(frozen=True)
class AdmissionClaim:
    run_id: str
    status: str
    conversation_id: int | None
    journal_available: bool
    acquired: bool


def claim_conversation_run(scope: str, fingerprint: str, user_id: str, tenant_id: str) -> AdmissionClaim:
    admission = ConversationRunAdmission
    with get_db_session() as session:
        if not tenant_membership_matches(session, user_id, tenant_id):
            raise AdmissionScopeError
        run_id = session.scalar(
            insert(admission).values(
                scope_sha256=scope, tenant_id=tenant_id, run_id=uuid4().hex, request_sha256=fingerprint,
                created_by=user_id, updated_by=user_id, delete_flag="N",
            ).on_conflict_do_nothing(index_elements=[admission.scope_sha256]).returning(admission.run_id)
        )
        if run_id is not None:
            return AdmissionClaim(run_id, "pending", None, False, True)

        existing = session.scalar(select(admission).where(admission.scope_sha256 == scope))
        if (
            existing is None or existing.delete_flag != "N"
            or existing.tenant_id != tenant_id or existing.created_by != user_id
        ):
            raise AdmissionScopeError
        if existing.request_sha256 != fingerprint:
            raise AdmissionRequestConflict
        return AdmissionClaim(existing.run_id, existing.status, existing.conversation_id, existing.journal_available, False)


def set_conversation_admission(
    scope: str, run_id: str, user_id: str, tenant_id: str, *,
    conversation_id: int | None, journal_available: bool,
) -> bool:
    """Record the first outcome of the matching pending claim."""
    admission = ConversationRunAdmission
    with get_db_session() as session:
        result = session.execute(
            update(admission).where(
                admission.scope_sha256 == scope,
                admission.run_id == run_id,
                admission.created_by == user_id,
                admission.tenant_id == tenant_id,
                admission.status == "pending",
                admission.delete_flag == "N",
            ).values(
                status="admitted" if conversation_id is not None else "rejected",
                conversation_id=conversation_id,
                journal_available=journal_available,
                updated_by=user_id,
                update_time=func.current_timestamp(),
            )
        )
        return result.rowcount == 1
