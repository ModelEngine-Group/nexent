"""PostgreSQL unit of work. Run-row locks serialize all dispatch/control decisions."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from .client import get_db_session
from .human_interaction_models import HumanEvent, HumanExecution, HumanRequest, HumanRun


ACTIVE_STATUSES = ("INITIALIZING", "READY", "RUNNING", "WAITING_HUMAN", "RECOVERY_REQUIRED")


def utcnow():
    return datetime.now(timezone.utc)


class RunTransaction:
    def __init__(self, session, run):
        self.session = session
        self.run = run

    def requests(self):
        return list(self.session.scalars(select(HumanRequest).where(HumanRequest.run_id == self.run.run_id)))

    def executions(self):
        return list(self.session.scalars(select(HumanExecution).where(HumanExecution.run_id == self.run.run_id)))

    def execution(self, slot):
        return self.session.get(HumanExecution, (self.run.run_id, slot))

    def add(self, value):
        self.session.add(value)
        self.session.flush()

    def emit(self, payload):
        self.run.event_seq += 1
        self.run.updated_at = utcnow()
        self.session.add(HumanEvent(
            run_id=self.run.run_id, seq=self.run.event_seq, payload=payload, created_at=utcnow(),
        ))


class HumanInteractionRepository:
    def __init__(self, session_factory=get_db_session):
        self.session_factory = session_factory

    @contextmanager
    def transaction(self, run_id, tenant_id=None, user_id=None):
        with self.session_factory() as session:
            conditions = [HumanRun.run_id == run_id]
            if tenant_id is not None:
                conditions.extend([HumanRun.tenant_id == tenant_id, HumanRun.user_id == user_id])
            run = session.scalar(select(HumanRun).where(*conditions).with_for_update())
            yield RunTransaction(session, run) if run else None

    def create(self, run):
        with self.session_factory() as session:
            session.add(run)
            session.flush()

    def latest(self, tenant_id, user_id, conversation_id, *, active_only=False):
        with self.session_factory() as session:
            conditions = [HumanRun.tenant_id == tenant_id, HumanRun.user_id == user_id,
                          HumanRun.conversation_id == conversation_id]
            if active_only:
                conditions.append(HumanRun.status.in_(ACTIVE_STATUSES))
            return session.scalar(select(HumanRun.run_id).where(*conditions).order_by(HumanRun.created_at.desc()))

    def events(self, run_id, after=0):
        with self.session_factory() as session:
            rows = session.scalars(select(HumanEvent).where(
                HumanEvent.run_id == run_id, HumanEvent.seq > after,
            ).order_by(HumanEvent.seq).limit(200))
            return [{"seq": row.seq, "payload": row.payload} for row in rows]

    def claim(self, owner_id, limit, seconds):
        with self.session_factory() as session:
            now = utcnow()
            abandoned = list(session.scalars(select(HumanRun).where(
                HumanRun.status == "INITIALIZING", HumanRun.created_at < now - timedelta(seconds=seconds),
            ).with_for_update(skip_locked=True).limit(limit)))
            for run in abandoned:
                run.status = "FAILED"
                RunTransaction(session, run).emit({"type": "human_run", "content": {
                    "run_id": run.run_id, "status": run.status,
                }})
            rows = list(session.scalars(select(HumanRun).where(
                or_(HumanRun.status == "READY", and_(HumanRun.status == "RUNNING", HumanRun.lock_until < now)),
                or_(HumanRun.lock_until.is_(None), HumanRun.lock_until < now),
            ).order_by(HumanRun.created_at).with_for_update(skip_locked=True).limit(limit)))
            result = []
            for run in rows:
                tx = RunTransaction(session, run)
                if any(item.status in {"STARTED", "UNKNOWN"} for item in tx.executions()):
                    run.status = "RECOVERY_REQUIRED"
                    tx.emit({"type": "human_run", "content": {"run_id": run.run_id, "status": run.status}})
                    continue
                run.status = "RUNNING"
                run.fence += 1
                run.lock_owner = owner_id
                run.lock_until = now + timedelta(seconds=seconds)
                result.append({"run_id": run.run_id, "tenant_id": run.tenant_id, "user_id": run.user_id,
                               "conversation_id": run.conversation_id, "fence": run.fence})
            return result

    def renew(self, run_id, owner_id, seconds):
        with self.transaction(run_id) as tx:
            if (tx is None or tx.run.lock_owner != owner_id or tx.run.lock_until is None
                    or tx.run.lock_until <= utcnow()):
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
            return list(session.scalars(select(HumanRun.run_id).where(HumanRun.status == "WAITING_HUMAN")))
