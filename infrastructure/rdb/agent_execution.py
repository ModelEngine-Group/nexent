# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime execution ledger and lease-based crash recovery."""

from dataclasses import dataclass
from threading import Lock
from uuid import uuid4

from sqlalchemy import Boolean, Column, Integer, String, TIMESTAMP, func, select, text, update
from sqlalchemy.dialects.postgresql import JSONB, insert

from infrastructure.rdb.base import SCHEMA, TableBase
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord
from infrastructure.rdb.conversation_state import tenant_membership_matches

OWNER_ID = uuid4().hex
LEASE_INTERVAL = text("interval '60 seconds'")
ACTIVE = ("starting", "running")
TERMINAL = ("completed", "failed", "stopped")
_live_run_ids: set[str] = set()
_live_run_lock = Lock()


class AgentExecution(TableBase):
    __tablename__ = "agent_execution_t"
    __table_args__ = {"schema": SCHEMA}

    run_id = Column(String(32), primary_key=True)
    conversation_id = Column(Integer, nullable=False)
    tenant_id = Column(String(100), nullable=False)
    owner_id = Column(String(32))
    lease_until = Column(TIMESTAMP(timezone=True))
    status = Column(String(16), nullable=False)
    cancellation_requested = Column(Boolean, nullable=False, server_default=text("false"))
    resource_versions = Column(JSONB, nullable=False, server_default=text("'{}'"))
    assistant_message_id = Column(Integer)
    journal_repair_pending = Column(Boolean, nullable=False, server_default=text("false"))


@dataclass(frozen=True)
class RunIdentity:
    tenant_id: str
    user_id: str
    conversation_id: int
    run_id: str


class ActiveExecutionError(Exception):
    """A conversation or execution ID already has an admitted run."""


def _scope(identity: RunIdentity):
    return (
        AgentExecution.run_id == identity.run_id,
        AgentExecution.conversation_id == identity.conversation_id,
        AgentExecution.tenant_id == identity.tenant_id,
        AgentExecution.created_by == identity.user_id,
        AgentExecution.delete_flag == "N",
    )


def _active():
    return (AgentExecution.status.in_(ACTIVE), AgentExecution.delete_flag == "N")


def _owned_conversation(session, conversation_id, user_id, tenant_id, *, lock=False):
    if not tenant_membership_matches(session, user_id, tenant_id):
        return False
    stmt = select(ConversationRecord.conversation_id).where(
        ConversationRecord.conversation_id == conversation_id, ConversationRecord.created_by == user_id,
        ConversationRecord.delete_flag == "N",
    )
    return session.scalar(stmt.with_for_update() if lock else stmt) is not None


def _insert_run(session, identity, **values):
    return session.scalar(insert(AgentExecution).values(
        run_id=identity.run_id, conversation_id=identity.conversation_id,
        tenant_id=identity.tenant_id, created_by=identity.user_id, updated_by=identity.user_id,
        delete_flag="N", **values,
    ).on_conflict_do_nothing(index_elements=[AgentExecution.run_id]).returning(AgentExecution.run_id))


def begin_execution(identity: RunIdentity) -> None:
    with get_db_session() as session:
        if not _owned_conversation(session, identity.conversation_id, identity.user_id, identity.tenant_id, lock=True):
            raise PermissionError("Conversation is not accessible")
        if session.scalar(select(AgentExecution.run_id).where(
            AgentExecution.conversation_id == identity.conversation_id, *_active(),
        ).limit(1)) is not None:
            raise ActiveExecutionError
        if _insert_run(session, identity, status="starting", owner_id=OWNER_ID,
                       lease_until=func.now() + LEASE_INTERVAL) is None:
            raise ActiveExecutionError


def track_execution(identity: RunIdentity) -> None:
    with _live_run_lock:
        _live_run_ids.add(identity.run_id)


def untrack_execution(identity: RunIdentity) -> None:
    with _live_run_lock:
        _live_run_ids.discard(identity.run_id)


def active_execution(conversation_id: int, user_id: str, tenant_id: str) -> str | None:
    with get_db_session() as session:
        if not _owned_conversation(session, conversation_id, user_id, tenant_id):
            raise PermissionError("Conversation is not accessible")
        return session.scalar(select(AgentExecution.run_id).where(
            AgentExecution.conversation_id == conversation_id, AgentExecution.created_by == user_id,
            AgentExecution.tenant_id == tenant_id, *_active(),
        ).limit(1))


def _snapshot(row):
    return {
        "conversation_id": row.conversation_id,
        "status": row.status,
        "resource_versions": row.resource_versions,
        "assistant_message_id": row.assistant_message_id,
        "cancellation_requested": row.status in ACTIVE and row.cancellation_requested,
    }


def read_execution(run_id, user_id, tenant_id, conversation_id=None, *, request_stop=False,
                   prevent_start=False) -> dict | None:
    with get_db_session() as session:
        if conversation_id is None:
            conversation_id = session.scalar(select(AgentExecution.conversation_id).where(
                AgentExecution.run_id == run_id, AgentExecution.created_by == user_id,
                AgentExecution.tenant_id == tenant_id, AgentExecution.delete_flag == "N",
            ))
            if conversation_id is None:
                return None
        identity = RunIdentity(tenant_id, user_id, conversation_id, run_id)
        if not _owned_conversation(session, identity.conversation_id, identity.user_id, identity.tenant_id,
                                   lock=request_stop):
            raise PermissionError("Conversation is not accessible")
        stmt = select(AgentExecution).where(*_scope(identity))
        row = session.scalar(stmt.with_for_update() if request_stop else stmt)
        if row is None and prevent_start:
            _insert_run(session, identity, status="stopped", cancellation_requested=True)
            row = session.scalar(stmt.with_for_update())
        if row is None:
            return None
        if request_stop and row.status in ACTIVE and not row.cancellation_requested:
            row.cancellation_requested = True
            row.updated_by = identity.user_id
        return _snapshot(row)


def _live_owner():
    return (AgentExecution.owner_id == OWNER_ID, AgentExecution.lease_until > func.now(), *_active())


def stop_requested(identity: RunIdentity) -> bool:
    with get_db_session() as session:
        conversation_exists = select(ConversationRecord.conversation_id).where(
            ConversationRecord.conversation_id == identity.conversation_id,
            ConversationRecord.created_by == identity.user_id,
            ConversationRecord.delete_flag == "N",
        ).exists()
        flag = session.scalar(select(AgentExecution.cancellation_requested).where(
            *_scope(identity), *_live_owner(), conversation_exists,
        ))
        return flag is not False


def mark_running(identity: RunIdentity, resource_versions: dict) -> bool:
    with get_db_session() as session:
        return bool(session.execute(update(AgentExecution).where(
            *_scope(identity), *_live_owner(), AgentExecution.cancellation_requested.is_(False),
        ).values(status="running", resource_versions=resource_versions)).rowcount)


def bind_assistant_message(session, identity: RunIdentity, message_id: int) -> None:
    if not session.execute(update(AgentExecution).where(
        *_scope(identity), *_live_owner(), AgentExecution.assistant_message_id.is_(None),
    ).values(assistant_message_id=message_id)).rowcount:
        raise RuntimeError("AgentOS execution no longer owns the assistant projection")


def finish_execution(identity: RunIdentity, status: str) -> bool:
    try:
        with get_db_session() as session:
            result = session.execute(update(AgentExecution).where(*_scope(identity), *_live_owner()).values(
                status=status, lease_until=None, journal_repair_pending=True,
            ))
            return bool(result.rowcount)
    finally:
        untrack_execution(identity)


def renew_execution_leases() -> None:
    with _live_run_lock:
        run_ids = tuple(_live_run_ids)
    if run_ids:
        with get_db_session() as session:
            session.execute(update(AgentExecution).where(
                AgentExecution.run_id.in_(run_ids), *_live_owner(),
            ).values(lease_until=func.now() + LEASE_INTERVAL))


def recover_expired_executions() -> int:
    with get_db_session() as session:
        rows = session.scalars(select(AgentExecution).where(
            *_active(), AgentExecution.lease_until <= func.now(),
        ).with_for_update(skip_locked=True).limit(100)).all()
        for row in rows:
            status = "stopped" if row.cancellation_requested else "failed"
            if row.assistant_message_id is not None:
                message = session.scalar(select(ConversationMessage).where(
                    ConversationMessage.message_id == row.assistant_message_id,
                    ConversationMessage.conversation_id == row.conversation_id,
                    ConversationMessage.created_by == row.created_by,
                    ConversationMessage.message_role == "assistant",
                    ConversationMessage.delete_flag == "N",
                ).with_for_update())
                if message is not None:
                    if message.status in TERMINAL:
                        status = message.status
                    elif message.status == "streaming":
                        message.status = status
            row.status = status
            row.lease_until = None
            row.journal_repair_pending = True
        return len(rows)


def pending_journal_repairs() -> list[tuple[RunIdentity, str]]:
    with get_db_session() as session:
        rows = session.scalars(select(AgentExecution).where(
            AgentExecution.journal_repair_pending.is_(True), AgentExecution.delete_flag == "N",
        ).order_by(AgentExecution.update_time).limit(100)).all()
        return [(RunIdentity(row.tenant_id, row.created_by, row.conversation_id, row.run_id), row.status) for row in rows]


def mark_journal_repaired(identity: RunIdentity) -> None:
    with get_db_session() as session:
        session.execute(update(AgentExecution).where(*_scope(identity)).values(journal_repair_pending=False))
