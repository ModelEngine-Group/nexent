from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, insert, select, text, update

from .client import as_dict, get_db_session
from .db_models import AgentAutomationProposal, AgentAutomationRun, AgentAutomationTask
from .utils import add_creation_tracking, add_update_tracking


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_task(task_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    data = {
        **task_data,
        "delete_flag": "N",
    }
    data = add_creation_tracking(data, user_id)
    with get_db_session() as session:
        stmt = insert(AgentAutomationTask).values(**data).returning(AgentAutomationTask)
        task = session.execute(stmt).scalar_one()
        return as_dict(task)


def get_task(task_id: int, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        task = session.execute(
            select(AgentAutomationTask).where(
                AgentAutomationTask.task_id == task_id,
                AgentAutomationTask.tenant_id == tenant_id,
                AgentAutomationTask.user_id == user_id,
                AgentAutomationTask.delete_flag == "N",
            )
        ).scalar_one_or_none()
        return as_dict(task) if task else None


def get_task_by_conversation(
    conversation_id: int,
    user_id: str,
    include_deleted: bool = False,
) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        conditions = [
            AgentAutomationTask.conversation_id == conversation_id,
            AgentAutomationTask.user_id == user_id,
        ]
        if not include_deleted:
            conditions.extend([
                AgentAutomationTask.delete_flag == "N",
                AgentAutomationTask.status != "DELETED",
            ])
        task = session.execute(select(AgentAutomationTask).where(*conditions)).scalar_one_or_none()
        return as_dict(task) if task else None


def list_tasks(tenant_id: str, user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        conditions = [
            AgentAutomationTask.tenant_id == tenant_id,
            AgentAutomationTask.user_id == user_id,
            AgentAutomationTask.delete_flag == "N",
            AgentAutomationTask.status != "DELETED",
        ]
        if status:
            conditions.append(AgentAutomationTask.status == status)
        rows = session.execute(
            select(AgentAutomationTask)
            .where(*conditions)
            .order_by(desc(AgentAutomationTask.update_time))
        ).scalars().all()
        return [as_dict(row) for row in rows]


def update_task(task_id: int, tenant_id: str, user_id: str, values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    data = add_update_tracking({
        **values,
        "update_time": _utcnow(),
    }, user_id)
    with get_db_session() as session:
        task = session.execute(
            update(AgentAutomationTask)
            .where(
                AgentAutomationTask.task_id == task_id,
                AgentAutomationTask.tenant_id == tenant_id,
                AgentAutomationTask.user_id == user_id,
                AgentAutomationTask.delete_flag == "N",
            )
            .values(**data)
            .returning(AgentAutomationTask)
        ).scalar_one_or_none()
        return as_dict(task) if task else None


def soft_delete_task(task_id: int, tenant_id: str, user_id: str) -> bool:
    result = update_task(task_id, tenant_id, user_id, {
        "status": "DELETED",
        "delete_flag": "Y",
        "lock_owner": None,
        "lock_until": None,
    })
    return result is not None


def soft_delete_task_by_conversation(conversation_id: int, user_id: str) -> int:
    with get_db_session() as session:
        result = session.execute(
            update(AgentAutomationTask)
            .where(
                AgentAutomationTask.conversation_id == conversation_id,
                AgentAutomationTask.user_id == user_id,
                AgentAutomationTask.delete_flag == "N",
            )
            .values(
                status="DELETED",
                delete_flag="Y",
                lock_owner=None,
                lock_until=None,
                update_time=_utcnow(),
                updated_by=user_id,
            )
        )
        return result.rowcount or 0


def create_proposal(proposal_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    data = add_creation_tracking({**proposal_data, "delete_flag": "N"}, user_id)
    with get_db_session() as session:
        stmt = insert(AgentAutomationProposal).values(**data).returning(AgentAutomationProposal)
        proposal = session.execute(stmt).scalar_one()
        return as_dict(proposal)


def get_proposal(proposal_id: int, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        proposal = session.execute(
            select(AgentAutomationProposal).where(
                AgentAutomationProposal.proposal_id == proposal_id,
                AgentAutomationProposal.tenant_id == tenant_id,
                AgentAutomationProposal.user_id == user_id,
                AgentAutomationProposal.delete_flag == "N",
            )
        ).scalar_one_or_none()
        return as_dict(proposal) if proposal else None


def update_proposal_status(proposal_id: int, tenant_id: str, user_id: str, status: str) -> bool:
    with get_db_session() as session:
        result = session.execute(
            update(AgentAutomationProposal)
            .where(
                AgentAutomationProposal.proposal_id == proposal_id,
                AgentAutomationProposal.tenant_id == tenant_id,
                AgentAutomationProposal.user_id == user_id,
                AgentAutomationProposal.delete_flag == "N",
            )
            .values(status=status, update_time=_utcnow(), updated_by=user_id)
        )
        return bool(result.rowcount)


def update_proposal_task(
    proposal_id: int,
    tenant_id: str,
    user_id: str,
    proposed_task: Dict[str, Any],
) -> bool:
    with get_db_session() as session:
        result = session.execute(
            update(AgentAutomationProposal)
            .where(
                AgentAutomationProposal.proposal_id == proposal_id,
                AgentAutomationProposal.tenant_id == tenant_id,
                AgentAutomationProposal.user_id == user_id,
                AgentAutomationProposal.delete_flag == "N",
            )
            .values(
                proposed_task=proposed_task,
                update_time=_utcnow(),
                updated_by=user_id,
            )
        )
        return bool(result.rowcount)


def create_run(run_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    data = add_creation_tracking({**run_data, "delete_flag": "N"}, user_id)
    with get_db_session() as session:
        stmt = insert(AgentAutomationRun).values(**data).returning(AgentAutomationRun)
        run = session.execute(stmt).scalar_one()
        return as_dict(run)


def update_run(
    run_id: int,
    values: Dict[str, Any],
    user_id: Optional[str] = None,
    expected_statuses: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    data = {
        **values,
        "update_time": _utcnow(),
    }
    if user_id:
        data = add_update_tracking(data, user_id)
    with get_db_session() as session:
        conditions = [
            AgentAutomationRun.run_id == run_id,
            AgentAutomationRun.delete_flag == "N",
        ]
        if expected_statuses:
            conditions.append(AgentAutomationRun.status.in_(expected_statuses))
        run = session.execute(
            update(AgentAutomationRun)
            .where(*conditions)
            .values(**data)
            .returning(AgentAutomationRun)
        ).scalar_one_or_none()
        return as_dict(run) if run else None


def get_run(run_id: int, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        run = session.execute(
            select(AgentAutomationRun).where(
                AgentAutomationRun.run_id == run_id,
                AgentAutomationRun.tenant_id == tenant_id,
                AgentAutomationRun.user_id == user_id,
                AgentAutomationRun.delete_flag == "N",
            )
        ).scalar_one_or_none()
        return as_dict(run) if run else None


def cancel_run(run_id: int, tenant_id: str, user_id: str, reason: str) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        run = session.execute(
            update(AgentAutomationRun)
            .where(
                AgentAutomationRun.run_id == run_id,
                AgentAutomationRun.tenant_id == tenant_id,
                AgentAutomationRun.user_id == user_id,
                AgentAutomationRun.status.in_(["QUEUED", "RUNNING"]),
                AgentAutomationRun.delete_flag == "N",
            )
            .values(
                status="CANCELED",
                error_code="AUTOMATION_RUN_CANCELED",
                error_message=reason,
                finished_at=_utcnow(),
                update_time=_utcnow(),
                updated_by=user_id,
            )
            .returning(AgentAutomationRun)
        ).scalar_one_or_none()
        return as_dict(run) if run else None


def cancel_runs_by_conversation(conversation_id: int, user_id: str, reason: str) -> int:
    with get_db_session() as session:
        result = session.execute(
            update(AgentAutomationRun)
            .where(
                AgentAutomationRun.conversation_id == conversation_id,
                AgentAutomationRun.user_id == user_id,
                AgentAutomationRun.status.in_(["QUEUED", "RUNNING"]),
                AgentAutomationRun.delete_flag == "N",
            )
            .values(
                status="CANCELED",
                error_code="AUTOMATION_RUN_CANCELED",
                error_message=reason,
                finished_at=_utcnow(),
                update_time=_utcnow(),
                updated_by=user_id,
            )
        )
        return result.rowcount or 0


def list_runs(task_id: int, tenant_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        rows = session.execute(
            select(AgentAutomationRun)
            .where(
                AgentAutomationRun.task_id == task_id,
                AgentAutomationRun.tenant_id == tenant_id,
                AgentAutomationRun.user_id == user_id,
                AgentAutomationRun.delete_flag == "N",
            )
            .order_by(desc(AgentAutomationRun.scheduled_fire_at))
            .limit(limit)
        ).scalars().all()
        return [as_dict(row) for row in rows]


def has_active_run_for_conversation(conversation_id: int) -> bool:
    with get_db_session() as session:
        run = session.execute(
            select(AgentAutomationRun.run_id)
            .where(
                AgentAutomationRun.conversation_id == conversation_id,
                AgentAutomationRun.status.in_(["QUEUED", "RUNNING"]),
                AgentAutomationRun.delete_flag == "N",
            )
            .limit(1)
        ).scalar_one_or_none()
        return run is not None


def claim_due_tasks(instance_id: str, batch_size: int, lease_seconds: int) -> List[Dict[str, Any]]:
    sql = text("""
        UPDATE nexent.agent_automation_task_t
        SET lock_owner = :instance_id,
            lock_until = now() + (:lease_seconds * interval '1 second'),
            update_time = now()
        WHERE task_id IN (
            SELECT task_id
            FROM nexent.agent_automation_task_t
            WHERE delete_flag = 'N'
              AND status = 'ACTIVE'
              AND next_fire_at <= now()
              AND (lock_until IS NULL OR lock_until < now())
            ORDER BY next_fire_at ASC
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        RETURNING *
    """)
    with get_db_session() as session:
        rows = session.execute(sql, {
            "instance_id": instance_id,
            "batch_size": batch_size,
            "lease_seconds": lease_seconds,
        }).fetchall()
        return [dict(row._mapping) for row in rows]


def release_task_lock(task_id: int, lock_owner: Optional[str] = None) -> bool:
    conditions = [AgentAutomationTask.task_id == task_id]
    if lock_owner:
        conditions.append(AgentAutomationTask.lock_owner == lock_owner)
    with get_db_session() as session:
        result = session.execute(
            update(AgentAutomationTask)
            .where(*conditions)
            .values(lock_owner=None, lock_until=None, update_time=_utcnow())
        )
        return bool(result.rowcount)


def renew_task_lock(task_id: int, lock_owner: str, lease_seconds: int) -> bool:
    with get_db_session() as session:
        result = session.execute(
            update(AgentAutomationTask)
            .where(
                AgentAutomationTask.task_id == task_id,
                AgentAutomationTask.lock_owner == lock_owner,
                AgentAutomationTask.delete_flag == "N",
                AgentAutomationTask.status == "ACTIVE",
            )
            .values(
                lock_until=_utcnow() + timedelta(seconds=lease_seconds),
                update_time=_utcnow(),
            )
        )
        return bool(result.rowcount)


def recover_stale_runs(timeout_seconds: int) -> int:
    sql = text("""
        UPDATE nexent.agent_automation_run_t
        SET status = 'TIMEOUT',
            error_code = 'AUTOMATION_RUN_TIMEOUT',
            error_message = 'Automation run timed out during runtime recovery.',
            finished_at = now(),
            update_time = now()
        WHERE delete_flag = 'N'
          AND status = 'RUNNING'
          AND started_at < now() - (:timeout_seconds * interval '1 second')
    """)
    with get_db_session() as session:
        result = session.execute(sql, {"timeout_seconds": timeout_seconds})
        return result.rowcount or 0


def release_expired_locks() -> int:
    with get_db_session() as session:
        result = session.execute(
            update(AgentAutomationTask)
            .where(
                AgentAutomationTask.delete_flag == "N",
                AgentAutomationTask.lock_until.is_not(None),
                AgentAutomationTask.lock_until < _utcnow(),
            )
            .values(lock_owner=None, lock_until=None, update_time=_utcnow())
        )
        return result.rowcount or 0
