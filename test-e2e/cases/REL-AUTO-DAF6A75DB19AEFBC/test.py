"""D5 reliability: startup recovery for interrupted no-set evaluation runs.

A no-set evaluation run (``evaluation_set_id == 0``) builds its temporary cases
in process memory and has no durable continuation point, so after a config/runtime
restart it would otherwise stay PENDING forever. This test drives
``fail_interrupted_no_set_runs_on_startup`` directly and verifies that it:

* fails a no-set PENDING run (delete_flag='N') and its PENDING case with the
  exact startup-recovery error message;
* leaves a soft-deleted no-set run (delete_flag='D') untouched;
* leaves a durable-set run (evaluation_set_id > 0) and its case untouched so it
  remains re-dispatchable by ``list_dispatchable_pending_runs``;
* is idempotent (a second call finds nothing left to fail).
"""

from __future__ import annotations

import pytest

from consts.evaluation_status import EvalCaseStatus, EvalRunStatus
from database.agent_evaluation_db import (
    fail_interrupted_no_set_runs_on_startup,
    list_dispatchable_pending_runs,
)
from database.client import get_db_session
from database.db_models import AgentEvaluation, AgentEvaluationCase


ERROR_MESSAGE = "Server restarted before evaluation execution started"

TENANT_ID = "nexent-test-d5-noset-recovery"
BASE_AGENT_ID = 987654321


def _no_set_pending_ids() -> set[int]:
    with get_db_session() as session:
        rows = (
            session.query(AgentEvaluation.agent_evaluation_id)
            .filter(
                AgentEvaluation.status == EvalRunStatus.PENDING,
                AgentEvaluation.evaluation_set_id == 0,
                AgentEvaluation.delete_flag == "N",
            )
            .all()
        )
    return {row[0] for row in rows}


def _cleanup_tenant_rows() -> None:
    with get_db_session() as session:
        run_ids = [
            row[0]
            for row in session.query(AgentEvaluation.agent_evaluation_id)
            .filter(AgentEvaluation.tenant_id == TENANT_ID)
            .all()
        ]
        if run_ids:
            session.query(AgentEvaluationCase).filter(
                AgentEvaluationCase.tenant_id == TENANT_ID,
                AgentEvaluationCase.agent_evaluation_id.in_(run_ids),
            ).delete(synchronize_session=False)
        session.query(AgentEvaluation).filter(
            AgentEvaluation.tenant_id == TENANT_ID
        ).delete(synchronize_session=False)
        session.commit()


def _insert_run(session, evaluation_set_id: int, delete_flag: str, agent_id: int) -> AgentEvaluation:
    rec = AgentEvaluation(
        tenant_id=TENANT_ID,
        agent_id=agent_id,
        agent_version_no=1,
        evaluation_set_id=evaluation_set_id,
        status=EvalRunStatus.PENDING,
        progress_total=1,
        progress_done=0,
        delete_flag=delete_flag,
        created_by="test",
        updated_by="test",
    )
    session.add(rec)
    session.flush()
    return rec


def _insert_case(session, agent_evaluation_id: int, evaluation_set_case_id: int) -> None:
    session.add(
        AgentEvaluationCase(
            tenant_id=TENANT_ID,
            agent_evaluation_id=agent_evaluation_id,
            evaluation_set_case_id=evaluation_set_case_id,
            inputs={"query": "test"},
            label={"answer": "expected"},
            status=EvalCaseStatus.PENDING,
            error_message=None,
            delete_flag="N",
            created_by="test",
            updated_by="test",
        )
    )
    session.flush()


def _get_run(agent_evaluation_id: int) -> tuple[str, str | None]:
    with get_db_session() as session:
        rec = (
            session.query(AgentEvaluation)
            .filter(AgentEvaluation.agent_evaluation_id == agent_evaluation_id)
            .first()
        )
        assert rec is not None, f"run {agent_evaluation_id} missing"
        return rec.status, rec.error_message


def _get_case(agent_evaluation_id: int) -> tuple[str, str | None]:
    with get_db_session() as session:
        rec = (
            session.query(AgentEvaluationCase)
            .filter(AgentEvaluationCase.agent_evaluation_id == agent_evaluation_id)
            .first()
        )
        assert rec is not None, f"case for run {agent_evaluation_id} missing"
        return rec.status, rec.error_message


@pytest.mark.stage("D5")
@pytest.mark.case_id("REL-AUTO-DAF6A75DB19AEFBC")
def test_fail_interrupted_no_set_runs_on_startup() -> None:
    _cleanup_tenant_rows()
    baseline = _no_set_pending_ids()

    a_id = b_id = c_id = None
    try:
        with get_db_session() as session:
            a = _insert_run(session, 0, "N", BASE_AGENT_ID)
            _insert_case(session, a.agent_evaluation_id, 1000000001)
            b = _insert_run(session, 0, "D", BASE_AGENT_ID + 1)
            c = _insert_run(session, 2000000000, "N", BASE_AGENT_ID + 2)
            _insert_case(session, c.agent_evaluation_id, 1000000002)
            a_id = int(a.agent_evaluation_id)
            b_id = int(b.agent_evaluation_id)
            c_id = int(c.agent_evaluation_id)

        processed = fail_interrupted_no_set_runs_on_startup()
        assert processed == len(baseline) + 1

        a_status, a_error = _get_run(a_id)
        b_status, b_error = _get_run(b_id)
        c_status, c_error = _get_run(c_id)
        a_case_status, a_case_error = _get_case(a_id)
        c_case_status, c_case_error = _get_case(c_id)

        assert a_status == EvalRunStatus.FAILED
        assert a_error == ERROR_MESSAGE
        assert a_case_status == EvalCaseStatus.FAILED
        assert a_case_error == ERROR_MESSAGE

        assert b_status == EvalRunStatus.PENDING
        assert b_error is None

        assert c_status == EvalRunStatus.PENDING
        assert c_error is None
        assert c_case_status == EvalCaseStatus.PENDING
        assert c_case_error is None

        dispatchable_ids = {
            row["agent_evaluation_id"] for row in list_dispatchable_pending_runs()
        }
        assert c_id in dispatchable_ids
        assert a_id not in dispatchable_ids

        second = fail_interrupted_no_set_runs_on_startup()
        assert second == 0
    finally:
        _cleanup_tenant_rows()
