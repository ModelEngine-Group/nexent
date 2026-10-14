from __future__ import annotations

import uuid
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from database.a2a_agent_db import _get_db_session, fail_active_tasks_on_startup
from database.db_models import A2ATask

CASE_ID = "REL-AUTO-0420654CDB5C783B"

ACTIVE_STATES = ("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING")

EXPECTED_RESULT = {
    "error": {
        "code": "CONTAINER_RESTARTED",
        "message": "Northbound service restarted before the task completed",
    }
}


def _new_task_id() -> str:
    return f"rel-auto-0420654-{uuid.uuid4().hex}"


def _build_task(task_id: str, task_state: str) -> A2ATask:
    return A2ATask(
        id=task_id,
        endpoint_id="rel-auto-0420654-endpoint",
        task_state=task_state,
        caller_user_id="rel-auto-0420654-user",
        caller_tenant_id="rel-auto-0420654-tenant",
        context_id=None,
        raw_request=None,
        state_timestamp=None,
        result_data=None,
    )


def _count_active(session) -> int:
    return (
        session.query(A2ATask)
        .filter(A2ATask.task_state.in_(ACTIVE_STATES))
        .count()
    )


def _as_utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _task_snapshot(task):
    # Materialize asserted scalar values while their Session is still open.
    return SimpleNamespace(**{field: getattr(task, field) for field in (
        'task_state', 'result_data', 'state_timestamp', 'completed_at', 'update_time'
    )})


@pytest.mark.stage("D5")
@pytest.mark.case_id(CASE_ID)
def test_startup_recovery_converges_legacy_a2a_tasks_to_failed():
    submitted_id = _new_task_id()
    working_id = _new_task_id()
    terminal_states = [
        "TASK_STATE_COMPLETED",
        "TASK_STATE_FAILED",
        "TASK_STATE_CANCELED",
    ]
    terminal_ids = [_new_task_id() for _ in terminal_states]
    active_ids = [submitted_id, working_id]
    inserted_ids = active_ids + terminal_ids

    with _get_db_session() as session:
        session.add(_build_task(submitted_id, "TASK_STATE_SUBMITTED"))
        session.add(_build_task(working_id, "TASK_STATE_WORKING"))
        for task_id, state in zip(terminal_ids, terminal_states):
            session.add(_build_task(task_id, state))

    pre_existing: list[tuple] = []
    try:
        with _get_db_session() as session:
            pre_existing = [
                (
                    t.id,
                    t.task_state,
                    t.state_timestamp,
                    t.result_data,
                    t.completed_at,
                    t.update_time,
                )
                for t in session.query(A2ATask)
                .filter(
                    A2ATask.task_state.in_(ACTIVE_STATES),
                    A2ATask.id.notin_(inserted_ids),
                )
                .all()
            ]
            active_before = _count_active(session)

        assert active_before >= 2

        before_ts = datetime.now(timezone.utc)
        affected = fail_active_tasks_on_startup()
        after_ts = datetime.now(timezone.utc)

        assert affected == active_before
        assert affected >= 2

        with _get_db_session() as session:
            rows = {
                t.id: _task_snapshot(t)
                for t in session.query(A2ATask)
                .filter(A2ATask.id.in_(inserted_ids))
                .all()
            }
            remaining = _count_active(session)

        assert remaining == 0

        for task_id, state in zip(terminal_ids, terminal_states):
            assert rows[task_id].task_state == state

        window = timedelta(seconds=10)
        for task_id in active_ids:
            task = rows[task_id]
            assert task.task_state == "TASK_STATE_FAILED"
            assert task.result_data == EXPECTED_RESULT
            for field in ("state_timestamp", "completed_at", "update_time"):
                value = _as_utc(getattr(task, field))
                assert value is not None
                assert isinstance(value, datetime)
                assert before_ts - window <= value <= after_ts + window

        second = fail_active_tasks_on_startup()
        assert second == 0
    finally:
        with _get_db_session() as session:
            session.query(A2ATask).filter(A2ATask.id.in_(inserted_ids)).delete(
                synchronize_session=False
            )
            for tid, state, st, rd, ca, ut in pre_existing:
                session.query(A2ATask).filter(A2ATask.id == tid).update(
                    {
                        "task_state": state,
                        "state_timestamp": st,
                        "result_data": rd,
                        "completed_at": ca,
                        "update_time": ut,
                    },
                    synchronize_session=False,
                )
