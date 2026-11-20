# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from management.db.execution.models import ExecutionReservation


ACTIVE_STATES = ("PREPARING", "RUNNING", "FINALIZING")
MAINTENANCE_ACTOR = "runtime-maintenance"


def lock_admission_scope(session: Session, kind: str, tenant_id: str, key: str) -> None:
    scope = json.dumps(("nexent:runtime:admission", kind, tenant_id, key), separators=(",", ":"))
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"), {"scope": scope})


def find_active_execution(session: Session, tenant_id: str, execution_key: str) -> ExecutionReservation | None:
    return session.scalar(
        select(ExecutionReservation)
        .where(
            ExecutionReservation.tenant_id == tenant_id,
            ExecutionReservation.execution_key == execution_key,
            ExecutionReservation.service_role == "runtime",
            ExecutionReservation.status.in_(ACTIVE_STATES),
            ExecutionReservation.delete_flag == "N",
        )
        .limit(1)
    )


def find_owned_agent_execution(
    session: Session, tenant_id: str, user_id: str, execution_key: str, *, active_only: bool,
) -> tuple[int, str, str | None] | None:
    query = select(ExecutionReservation.execution_id, ExecutionReservation.status, ExecutionReservation.agent_scope).where(
        ExecutionReservation.tenant_id == tenant_id,
        ExecutionReservation.user_id == user_id,
        ExecutionReservation.execution_key == execution_key,
        ExecutionReservation.execution_kind == "agent",
        ExecutionReservation.service_role == "runtime",
        ExecutionReservation.delete_flag == "N",
    )
    if active_only:
        query = query.where(ExecutionReservation.status.in_(ACTIVE_STATES))
    row = session.execute(query.order_by(ExecutionReservation.execution_id.desc()).limit(1)).one_or_none()
    return (row.execution_id, row.status, row.agent_scope) if row else None


def count_active_agent_executions(session: Session, tenant_id: str, agent_scope: str) -> int:
    return session.scalar(
        select(func.count()).select_from(ExecutionReservation).where(
            ExecutionReservation.tenant_id == tenant_id,
            ExecutionReservation.agent_scope == agent_scope,
            ExecutionReservation.service_role == "runtime",
            ExecutionReservation.execution_kind == "agent",
            ExecutionReservation.status.in_(ACTIVE_STATES),
            ExecutionReservation.delete_flag == "N",
        )
    )


def insert_preparing_execution(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    execution_kind: str,
    execution_key: str,
    agent_scope: str | None,
    owner_instance_id: str,
    maintenance_epoch: str,
) -> int:
    record = ExecutionReservation(
        tenant_id=tenant_id,
        user_id=user_id,
        execution_kind=execution_kind,
        execution_key=execution_key,
        agent_scope=agent_scope,
        service_role="runtime",
        owner_instance_id=owner_instance_id,
        maintenance_epoch=maintenance_epoch,
        status="PREPARING",
        created_by=user_id,
        updated_by=user_id,
        delete_flag="N",
    )
    session.add(record)
    session.flush()
    return record.execution_id


def transition_owned_execution(
    session: Session,
    execution_id: int,
    owner_instance_id: str,
    expected_states: tuple[str, ...],
    status: str,
    error_code: str | None,
) -> bool:
    now = func.timezone("UTC", func.clock_timestamp())
    values = {
        "status": status,
        "update_time": now,
        "updated_by": ExecutionReservation.user_id,
        "error_code": error_code,
    }
    if status == "RUNNING":
        values["started_at"] = now
    elif status not in ACTIVE_STATES:
        values["finished_at"] = now
    execution = session.scalar(
        update(ExecutionReservation)
        .where(
            ExecutionReservation.execution_id == execution_id,
            ExecutionReservation.owner_instance_id == owner_instance_id,
            ExecutionReservation.status.in_(expected_states),
            ExecutionReservation.service_role == "runtime",
            ExecutionReservation.execution_kind.in_(("agent", "evaluation")),
            ExecutionReservation.delete_flag == "N",
        )
        .values(**values)
        .returning(ExecutionReservation.execution_id)
    )
    return execution is not None


def lock_maintenance(session: Session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('nexent:runtime:maintenance', 0))"))


def maintenance_completed_at(session: Session, epoch: str) -> datetime | None:
    return session.scalar(
        select(ExecutionReservation.finished_at)
        .where(
            ExecutionReservation.maintenance_epoch == epoch,
            ExecutionReservation.execution_kind == "maintenance",
            ExecutionReservation.service_role == "runtime",
            ExecutionReservation.status == "COMPLETED",
            ExecutionReservation.delete_flag == "N",
        )
        .order_by(ExecutionReservation.execution_id.desc())
        .limit(1)
    )


def interrupt_active_executions(session: Session) -> None:
    now = func.timezone("UTC", func.clock_timestamp())
    session.execute(
        update(ExecutionReservation)
        .where(
            ExecutionReservation.service_role == "runtime",
            ExecutionReservation.execution_kind.in_(("agent", "evaluation")),
            ExecutionReservation.status.in_(ACTIVE_STATES),
            ExecutionReservation.delete_flag == "N",
        )
        .values(
            status="FAILED",
            error_code="RUNTIME_OWNER_INTERRUPTED",
            finished_at=now,
            update_time=now,
            updated_by=MAINTENANCE_ACTOR,
        )
    )


def record_maintenance_completion(session: Session, epoch: str, owner_instance_id: str) -> None:
    session.add(
        ExecutionReservation(
            execution_kind="maintenance",
            service_role="runtime",
            execution_key=f"maintenance:{epoch}",
            owner_instance_id=owner_instance_id,
            maintenance_epoch=epoch,
            status="COMPLETED",
            finished_at=func.timezone("UTC", func.clock_timestamp()),
            created_by=MAINTENANCE_ACTOR,
            updated_by=MAINTENANCE_ACTOR,
            delete_flag="N",
        )
    )
