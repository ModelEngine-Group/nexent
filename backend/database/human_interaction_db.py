"""PostgreSQL unit of work; scoped locks serialize creation and run mutations."""

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, text, update

from .client import get_db_session
from .db_models import (
    ConversationRecord,
    HumanEvent,
    HumanExecution,
    HumanRequest,
    HumanRun,
)

ACTIVE_STATUSES = ("INITIALIZING", "READY", "RUNNING", "WAITING_HUMAN", "RECOVERY_REQUIRED")
HUMAN_MODELS = (HumanRun, HumanRequest, HumanExecution, HumanEvent)


def utcnow():
    return datetime.now(timezone.utc)


def audit_now():
    """Store shared TIMESTAMP audit columns as UTC without a timezone offset."""
    return utcnow().replace(tzinfo=None)


def _lock(session, scope):
    key = int.from_bytes(hashlib.sha256(json.dumps(scope).encode()).digest()[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


class RunTransaction:
    def __init__(self, session, run, validator, actor=None):
        self.session = session
        self.run = run
        self.validator = validator
        self.actor = actor or "system:hitl"
        self.event_floor = run.event_seq or 0

    def requests(self):
        return list(
            self.session.scalars(
                select(HumanRequest).where(
                    HumanRequest.run_record_id == self.run.run_record_id,
                    HumanRequest.delete_flag == "N",
                )
            )
        )

    def executions(self):
        return list(
            self.session.scalars(
                select(HumanExecution).where(
                    HumanExecution.run_record_id == self.run.run_record_id,
                    HumanExecution.delete_flag == "N",
                )
            )
        )

    def execution(self, slot):
        return self.session.scalar(
            select(HumanExecution).where(
                HumanExecution.run_record_id == self.run.run_record_id,
                HumanExecution.slot == slot,
                HumanExecution.delete_flag == "N",
            )
        )

    def conversation_exists(self):
        return (
            self.session.scalar(
                select(ConversationRecord.conversation_id)
                .where(
                    ConversationRecord.conversation_id == self.run.conversation_id,
                    ConversationRecord.created_by == self.run.user_id,
                    ConversationRecord.delete_flag == "N",
                )
                .with_for_update()
            )
            is not None
        )

    def active_run_exists(self):
        return (
            self.session.scalar(
                select(HumanRun.run_record_id).where(
                    HumanRun.tenant_id == self.run.tenant_id,
                    HumanRun.user_id == self.run.user_id,
                    HumanRun.conversation_id == self.run.conversation_id,
                    HumanRun.status.in_(ACTIVE_STATUSES),
                    HumanRun.delete_flag == "N",
                )
            )
            is not None
        )

    def run_id_exists(self):
        # Public run identities must not alias even a retained, deleted run.
        return (
            self.session.scalar(
                select(HumanRun.run_record_id).where(
                    HumanRun.run_id == self.run.run_id,
                )
            )
            is not None
        )

    def add(self, value):
        self.session.add(value)
        self.flush()

    def _prepare(self, value, *, creating):
        now = audit_now()
        if creating:
            value.created_by = value.updated_by = self.actor
            value.create_time = value.update_time = now
            value.delete_flag = "N"
        else:
            value.updated_by = self.actor
            value.update_time = now
        self.validator(value, self, creating=creating)

    def flush(self):
        if self.run.delete_flag == "Y":
            self._prepare(self.run, creating=False)
            for model in (HumanRequest, HumanExecution, HumanEvent):
                self.session.execute(
                    update(model)
                    .where(
                        model.run_record_id == self.run.run_record_id,
                        model.delete_flag == "N",
                    )
                    .values(delete_flag="Y", updated_by=self.actor, update_time=audit_now())
                )
        for value in list(self.session.new):
            if isinstance(value, HUMAN_MODELS):
                self._prepare(value, creating=True)
        for value in list(self.session.dirty):
            if isinstance(value, HUMAN_MODELS) and self.session.is_modified(value):
                self._prepare(value, creating=False)
        self.session.flush()

    def emit(self, payload):
        self.run.event_seq += 1
        event = HumanEvent(run_record_id=self.run.run_record_id, seq=self.run.event_seq, payload=payload)
        self.session.add(event)


class HumanInteractionRepository:
    def __init__(self, session_factory=get_db_session):
        self.session_factory = session_factory
        self.validator = None

    @contextmanager
    def transaction(self, run_id, tenant_id=None, user_id=None):
        with self.session_factory() as session, session.no_autoflush:
            conditions = [HumanRun.run_id == run_id, HumanRun.delete_flag == "N"]
            if tenant_id is not None:
                conditions.extend([HumanRun.tenant_id == tenant_id, HumanRun.user_id == user_id])
            run = session.scalar(select(HumanRun).where(*conditions).with_for_update())
            tx = RunTransaction(session, run, self.validator, user_id) if run else None
            yield tx
            if tx:
                tx.flush()

    @contextmanager
    def creation(self, run):
        with self.session_factory() as session, session.no_autoflush:
            _lock(session, ["human-run-id", run.run_id])
            _lock(session, ["human-conversation", run.tenant_id, run.user_id, run.conversation_id])
            tx = RunTransaction(session, run, self.validator, run.user_id)
            tx._prepare(run, creating=True)
            yield tx
            tx.flush()

    def latest(self, tenant_id, user_id, conversation_id, *, active_only=False):
        with self.session_factory() as session:
            conditions = [
                HumanRun.tenant_id == tenant_id,
                HumanRun.user_id == user_id,
                HumanRun.conversation_id == conversation_id,
                HumanRun.delete_flag == "N",
            ]
            if active_only:
                conditions.append(HumanRun.status.in_(ACTIVE_STATUSES))
            return session.scalar(
                select(HumanRun.run_id)
                .where(*conditions)
                .order_by(
                    HumanRun.create_time.desc(),
                    HumanRun.run_record_id.desc(),
                )
                .limit(1)
            )

    def events(self, run_id, after=0):
        with self.session_factory() as session:
            rows = session.scalars(
                select(HumanEvent)
                .join(
                    HumanRun,
                    HumanRun.run_record_id == HumanEvent.run_record_id,
                )
                .where(
                    HumanRun.run_id == run_id,
                    HumanRun.delete_flag == "N",
                    HumanEvent.delete_flag == "N",
                    HumanEvent.seq > after,
                )
                .order_by(HumanEvent.seq)
                .limit(200)
            )
            return [{"seq": row.seq, "payload": row.payload} for row in rows]

    def claim(self, owner_id, limit, seconds):
        with self.session_factory() as session, session.no_autoflush:
            now = utcnow()
            abandoned = list(
                session.scalars(
                    select(HumanRun)
                    .where(
                        HumanRun.delete_flag == "N",
                        HumanRun.status == "INITIALIZING",
                        HumanRun.create_time < audit_now() - timedelta(seconds=seconds),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            )
            for run in abandoned:
                run.status = "FAILED"
                tx = RunTransaction(session, run, self.validator)
                tx.emit(
                    {
                        "type": "human_run",
                        "content": {
                            "run_id": run.run_id,
                            "status": run.status,
                        },
                    }
                )
                tx.flush()
            rows = list(
                session.scalars(
                    select(HumanRun)
                    .where(
                        HumanRun.delete_flag == "N",
                        or_(HumanRun.status == "READY", and_(HumanRun.status == "RUNNING", HumanRun.lock_until < now)),
                        or_(HumanRun.lock_until.is_(None), HumanRun.lock_until < now),
                    )
                    .order_by(HumanRun.create_time)
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            )
            result = []
            for run in rows:
                tx = RunTransaction(session, run, self.validator)
                if any(item.status in {"STARTED", "UNKNOWN"} for item in tx.executions()):
                    run.status = "RECOVERY_REQUIRED"
                    tx.emit({"type": "human_run", "content": {"run_id": run.run_id, "status": run.status}})
                    tx.flush()
                    continue
                run.status = "RUNNING"
                run.fence += 1
                run.lock_owner = owner_id
                run.lock_until = now + timedelta(seconds=seconds)
                tx.flush()
                result.append(
                    {
                        "run_id": run.run_id,
                        "tenant_id": run.tenant_id,
                        "user_id": run.user_id,
                        "conversation_id": run.conversation_id,
                        "fence": run.fence,
                    }
                )
            return result

    def renew(self, run_id, owner_id, seconds):
        with self.transaction(run_id) as tx:
            if (
                tx is None
                or tx.run.lock_owner != owner_id
                or tx.run.lock_until is None
                or tx.run.lock_until <= utcnow()
            ):
                return False
            tx.run.lock_until = utcnow() + timedelta(seconds=seconds)
            return True

    def release(self, run_id, owner_id):
        with self.transaction(run_id) as tx:
            if tx is None or tx.run.lock_owner != owner_id:
                return False
            tx.run.lock_owner = None
            tx.run.lock_until = None
            if tx.run.status == "RUNNING":
                tx.run.status = "RECOVERY_REQUIRED"
                tx.emit({"type": "human_run", "content": {"run_id": run_id, "status": tx.run.status}})
            return True

    def waiting_ids(self):
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(HumanRun.run_id).where(
                        HumanRun.status == "WAITING_HUMAN",
                        HumanRun.delete_flag == "N",
                    )
                )
            )
