from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from shared.postgres import postgres_target

_CASE_ID = 'REL-AUTO-DAED0399BC7F3CAB'
_ERROR_MESSAGE = 'Server restarted — evaluation was interrupted'
_TIMEOUT_MINUTES = 10


def _apply_db_environment():
    target = postgres_target()
    for key, value in {
        'POSTGRES_HOST': target.host,
        'POSTGRES_PORT': target.port,
        'POSTGRES_USER': target.user,
        'POSTGRES_DB': target.database,
        'NEXENT_POSTGRES_PASSWORD': target.password,
    }.items():
        if value is not None:
            os.environ[key] = str(value)


_apply_db_environment()

from database.agent_evaluation_db import reap_stale_runs  # noqa: E402
from database.client import get_db_session  # noqa: E402
from database.db_models import AgentEvaluation, AgentEvaluationCase  # noqa: E402


def _naive_utc(delta_minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)).replace(tzinfo=None)


def _insert_run(session, tenant_id, status, update_time, progress_total=1):
    rec = AgentEvaluation(
        tenant_id=tenant_id,
        agent_id=1,
        agent_version_no=1,
        evaluation_set_id=1,
        status=status,
        progress_total=progress_total,
        progress_done=0,
        update_time=update_time,
        created_by='rel-auto',
        updated_by='rel-auto',
        delete_flag='N',
    )
    session.add(rec)
    session.flush()
    return rec.agent_evaluation_id


def _insert_case(session, tenant_id, run_id, set_case_id, status, error_message=None):
    rec = AgentEvaluationCase(
        tenant_id=tenant_id,
        agent_evaluation_id=run_id,
        evaluation_set_case_id=set_case_id,
        inputs={},
        label={},
        status=status,
        error_message=error_message,
        created_by='rel-auto',
        updated_by='rel-auto',
        delete_flag='N',
    )
    session.add(rec)
    session.flush()
    return rec.agent_evaluation_case_id


def _fetch_run(session, tenant_id, run_id):
    return (
        session.query(AgentEvaluation)
        .filter(
            AgentEvaluation.tenant_id == tenant_id,
            AgentEvaluation.agent_evaluation_id == run_id,
        )
        .first()
    )


def _fetch_case(session, tenant_id, case_id):
    return (
        session.query(AgentEvaluationCase)
        .filter(
            AgentEvaluationCase.tenant_id == tenant_id,
            AgentEvaluationCase.agent_evaluation_case_id == case_id,
        )
        .first()
    )


@pytest.mark.case_id(_CASE_ID)
@pytest.mark.stage('D5')
def test_reap_stale_runs_synchronizes_cases_and_preserves_tenants():
    tenant_a = f'rel-auto-reap-a-{uuid.uuid4().hex}'
    tenant_b = f'rel-auto-reap-b-{uuid.uuid4().hex}'
    stale_time = _naive_utc(-11)
    fresh_time = _naive_utc(-5)
    created_runs = []

    with get_db_session() as session:
        run_stale_id = _insert_run(session, tenant_a, 'RUNNING', stale_time, progress_total=3)
        case_pending_id = _insert_case(session, tenant_a, run_stale_id, 1, 'PENDING')
        case_running_id = _insert_case(session, tenant_a, run_stale_id, 2, 'RUNNING')
        case_done_id = _insert_case(session, tenant_a, run_stale_id, 3, 'SUCCEEDED')

        run_fresh_id = _insert_run(session, tenant_a, 'RUNNING', fresh_time, progress_total=1)
        case_pending2_id = _insert_case(session, tenant_a, run_fresh_id, 10, 'PENDING')

        run_other_id = _insert_run(session, tenant_b, 'RUNNING', stale_time, progress_total=1)
        case_other_id = _insert_case(session, tenant_b, run_other_id, 20, 'RUNNING')

        created_runs = [
            (tenant_a, run_stale_id),
            (tenant_a, run_fresh_id),
            (tenant_b, run_other_id),
        ]

    try:
        count = reap_stale_runs(tenant_id=tenant_a, timeout_minutes=_TIMEOUT_MINUTES)
        assert count == 1

        with get_db_session() as session:
            run_stale = _fetch_run(session, tenant_a, run_stale_id)
            assert run_stale.status == 'FAILED'
            assert run_stale.error_message == _ERROR_MESSAGE
            assert run_stale.update_time > stale_time

            case_pending = _fetch_case(session, tenant_a, case_pending_id)
            assert case_pending.status == 'FAILED'
            assert case_pending.error_message == _ERROR_MESSAGE

            case_running = _fetch_case(session, tenant_a, case_running_id)
            assert case_running.status == 'FAILED'
            assert case_running.error_message == _ERROR_MESSAGE

            case_done = _fetch_case(session, tenant_a, case_done_id)
            assert case_done.status == 'SUCCEEDED'
            assert case_done.error_message is None

            run_fresh = _fetch_run(session, tenant_a, run_fresh_id)
            assert run_fresh.status == 'RUNNING'

            case_pending2 = _fetch_case(session, tenant_a, case_pending2_id)
            assert case_pending2.status == 'PENDING'

            run_other = _fetch_run(session, tenant_b, run_other_id)
            assert run_other.status == 'RUNNING'
            assert run_other.error_message is None

            case_other = _fetch_case(session, tenant_b, case_other_id)
            assert case_other.status == 'RUNNING'
            assert case_other.error_message is None

        second_count = reap_stale_runs(tenant_id=tenant_a, timeout_minutes=_TIMEOUT_MINUTES)
        assert second_count == 0
    finally:
        with get_db_session() as session:
            for tenant, run_id in created_runs:
                session.query(AgentEvaluationCase).filter(
                    AgentEvaluationCase.tenant_id == tenant,
                    AgentEvaluationCase.agent_evaluation_id == run_id,
                ).delete(synchronize_session=False)
                session.query(AgentEvaluation).filter(
                    AgentEvaluation.tenant_id == tenant,
                    AgentEvaluation.agent_evaluation_id == run_id,
                ).delete(synchronize_session=False)
