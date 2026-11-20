# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Coordinate root Runtime executions across processes without migrating workers."""

import socket
from contextlib import nullcontext
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from contracts.errors.exceptions import RuntimeCoordinationUnavailableError
from infrastructure.rdb.client import get_db_session
from management.db.execution import repository


RUNTIME_OWNER_INSTANCE_ID = f"{socket.gethostname()[:63]}:{uuid4().hex}"


class ExecutionAlreadyActiveError(RuntimeError):
    """The business key already owns an active execution."""


class ExecutionQuotaExceededError(RuntimeError):
    """The shared Agent quota has no free slots."""


def reserve_runtime_execution(
    *,
    tenant_id: str,
    user_id: str,
    execution_kind: str,
    execution_key: str,
    agent_scope: str | None,
    agent_limit: int | None,
    owner_instance_id: str,
    maintenance_epoch: str,
    db_session: Session | None = None,
) -> int:
    """Reserve a business key and, for an Agent root, one slot in its tenant quota."""
    if execution_kind not in {"agent", "evaluation"}:
        raise ValueError("Unsupported Runtime execution kind")
    if any(not value or len(value) > limit for value, limit in (
        (tenant_id, 100), (user_id, 100), (execution_key, 64), (owner_instance_id, 100), (maintenance_epoch, 36),
    )):
        raise ValueError("Invalid Runtime execution identity")
    if execution_kind == "agent" and (not agent_scope or len(agent_scope) > 100 or not agent_limit or agent_limit < 1):
        raise ValueError("Agent execution requires a quota scope and a positive limit")
    if execution_kind == "evaluation" and (agent_scope is not None or agent_limit is not None):
        raise ValueError("Evaluation execution does not consume Agent quota")

    try:
        with (get_db_session() if db_session is None else nullcontext(db_session)) as session:
            if agent_scope is not None:
                repository.lock_admission_scope(session, "agent", tenant_id, agent_scope)
            repository.lock_admission_scope(session, "execution", tenant_id, execution_key)
            if repository.find_active_execution(session, tenant_id, execution_key) is not None:
                rejection = ExecutionAlreadyActiveError("A Runtime execution is already active")
            elif agent_scope is not None and agent_limit is not None and (
                repository.count_active_agent_executions(session, tenant_id, agent_scope) >= agent_limit
            ):
                rejection = ExecutionQuotaExceededError("The Agent has reached its concurrent execution limit")
            else:
                return repository.insert_preparing_execution(
                    session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    execution_kind=execution_kind,
                    execution_key=execution_key,
                    agent_scope=agent_scope,
                    owner_instance_id=owner_instance_id,
                    maintenance_epoch=maintenance_epoch,
                )
    except SQLAlchemyError as exc:
        raise RuntimeCoordinationUnavailableError("Runtime execution coordination is unavailable") from exc
    raise rejection


_STATUS_PREDECESSORS = {
    "RUNNING": ("PREPARING",),
    "FINALIZING": ("RUNNING",),
    "COMPLETED": ("FINALIZING",),
    "FAILED": repository.ACTIVE_STATES,
    "STOPPED": repository.ACTIVE_STATES,
}


def transition_runtime_execution(
    execution_id: int, owner_instance_id: str, status: str, *, error_code: str | None = None,
    db_session: Session | None = None,
) -> bool:
    """Reject a late transition unless it still owns the expected execution state."""
    if status not in _STATUS_PREDECESSORS:
        raise ValueError("Unsupported Runtime execution transition")
    if error_code is not None and (status != "FAILED" or len(error_code) > 100):
        raise ValueError("Invalid Runtime execution error code")
    try:
        with (get_db_session() if db_session is None else nullcontext(db_session)) as session:
            return repository.transition_owned_execution(
                session, execution_id, owner_instance_id, _STATUS_PREDECESSORS[status], status, error_code,
            )
    except SQLAlchemyError as exc:
        raise RuntimeCoordinationUnavailableError("Runtime execution coordination is unavailable") from exc


def read_owned_agent_execution(
    tenant_id: str, user_id: str, identifier: int | str, *, active_only: bool = False,
) -> tuple[int, str, str | None] | None:
    try:
        with get_db_session() as session:
            return repository.find_owned_agent_execution(
                session, tenant_id, user_id, f"conversation:{identifier}", active_only=active_only,
            )
    except SQLAlchemyError as exc:
        raise RuntimeCoordinationUnavailableError("Runtime execution coordination is unavailable") from exc
