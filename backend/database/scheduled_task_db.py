import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update

from .client import as_dict, get_db_session
from .db_models import ScheduledTaskRecord

logger = logging.getLogger("scheduled_task_db")


def create_scheduled_task(data: dict) -> dict:
    """Insert a new scheduled task record and return it as a dict."""
    with get_db_session() as session:
        record = ScheduledTaskRecord(**data)
        session.add(record)
        session.flush()
        return as_dict(record)


def query_tasks_by_agent(agent_id: int, tenant_id: str, user_id: str = None) -> list[dict]:
    """Return pending tasks for a given agent and tenant, optionally filtered by user."""
    with get_db_session() as session:
        stmt = select(ScheduledTaskRecord).where(
            ScheduledTaskRecord.agent_id == agent_id,
            ScheduledTaskRecord.tenant_id == tenant_id,
            ScheduledTaskRecord.status == "pending",
            ScheduledTaskRecord.delete_flag == "N",
        )
        if user_id:
            stmt = stmt.where(ScheduledTaskRecord.user_id == user_id)
        stmt = stmt.order_by(ScheduledTaskRecord.task_id.desc())
        records = session.scalars(stmt).all()
        return [as_dict(r) for r in records]


def query_pending_tasks_due(now: datetime) -> list[dict]:
    """Return all pending tasks whose next_fire_time <= now (global, no tenant filter)."""
    with get_db_session() as session:
        stmt = select(ScheduledTaskRecord).where(
            ScheduledTaskRecord.status == "pending",
            ScheduledTaskRecord.next_fire_time <= now,
            ScheduledTaskRecord.delete_flag == "N",
        )
        records = session.scalars(stmt).all()
        return [as_dict(r) for r in records]


def cancel_task(task_uuid: str, agent_id: int, tenant_id: str, user_id: str = None) -> bool:
    """Soft-cancel a task. Optionally restrict to a specific user for isolation.

    Cancels tasks in the 'pending' or 'fired' state, so a task can be
    cancelled even while it is currently executing.
    """
    with get_db_session() as session:
        conditions = [
            ScheduledTaskRecord.task_uuid == task_uuid,
            ScheduledTaskRecord.agent_id == agent_id,
            ScheduledTaskRecord.tenant_id == tenant_id,
            ScheduledTaskRecord.delete_flag == "N",
            ScheduledTaskRecord.status.in_(["pending", "fired"]),
        ]
        if user_id:
            conditions.append(ScheduledTaskRecord.user_id == user_id)
        stmt = (
            update(ScheduledTaskRecord)
            .where(*conditions)
            .values(status="cancelled")
        )
        result = session.execute(stmt)
        return result.rowcount > 0


def reschedule_if_active(task_uuid: str, fire_count: int, next_fire_time) -> bool:
    """Re-arm a cron task for its next fire, unless it was cancelled mid-run.

    Atomically sets status back to 'pending' (and advances fire_count /
    next_fire_time) only when the task is still in the 'fired' state — i.e. it
    has not been cancelled or marked errored while executing. Returns True if
    the task was re-armed.
    """
    with get_db_session() as session:
        stmt = (
            update(ScheduledTaskRecord)
            .where(
                ScheduledTaskRecord.task_uuid == task_uuid,
                ScheduledTaskRecord.status == "fired",
            )
            .values(
                status="pending",
                fire_count=fire_count,
                next_fire_time=next_fire_time,
            )
        )
        result = session.execute(stmt)
        return result.rowcount > 0


def update_task_status(task_uuid: str, updates: dict) -> None:
    """Update arbitrary columns on a task record identified by task_uuid."""
    with get_db_session() as session:
        stmt = (
            update(ScheduledTaskRecord)
            .where(
                ScheduledTaskRecord.task_uuid == task_uuid,
                ScheduledTaskRecord.delete_flag == "N",
            )
            .values(**updates)
        )
        session.execute(stmt)
