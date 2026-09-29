'''D1 BE-UT: materialize_virtual_evaluation_set_for_run 单事务物化语义。'''

import uuid

import pytest
from shared.resource_ids import absent_numeric_id
from shared.postgres import apply_product_postgres_env

# Nexent resolves DB constants during module import, so the shared deployment
# target must be injected before importing any product database module.
apply_product_postgres_env()

from consts.error_code import ErrorCode
from consts.evaluation_status import EvalRunStatus
from consts.exceptions import AppException
from database.client import get_db_session
from database.db_models import AgentEvaluation, EvaluationSet, EvaluationSetCase
from database.evaluation_set_db import materialize_virtual_evaluation_set_for_run


CASE_ID = 'UT-BE-AUTO-C0F44F945573C769'
STAGE = 'D1'


def _unique_tenant() -> str:
    return f'ut-no-set-{uuid.uuid4().hex[:16]}'


def _insert_agent_evaluation(tenant_id: str, status: str) -> int:
    with get_db_session() as session:
        rec = AgentEvaluation(
            tenant_id=tenant_id,
            agent_id=1,
            agent_version_no=0,
            evaluation_set_id=0,
            status=status,
            delete_flag='N',
        )
        session.add(rec)
        session.flush()
        return int(rec.agent_evaluation_id)


def _count_rows(tenant_id: str) -> tuple[int, int]:
    with get_db_session() as session:
        set_count = (
            session.query(EvaluationSet)
            .filter(EvaluationSet.tenant_id == tenant_id)
            .count()
        )
        case_count = (
            session.query(EvaluationSetCase)
            .filter(EvaluationSetCase.tenant_id == tenant_id)
            .count()
        )
        return set_count, case_count


def _cleanup_tenant(tenant_id: str) -> None:
    with get_db_session() as session:
        session.query(EvaluationSetCase).filter(
            EvaluationSetCase.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        session.query(EvaluationSet).filter(
            EvaluationSet.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        session.query(AgentEvaluation).filter(
            AgentEvaluation.tenant_id == tenant_id
        ).delete(synchronize_session=False)


@pytest.fixture
def isolated_tenant() -> str:
    tenant_id = _unique_tenant()
    yield tenant_id
    _cleanup_tenant(tenant_id)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage(STAGE)
def test_materialize_virtual_evaluation_set_for_run(isolated_tenant: str) -> None:
    tenant_id = isolated_tenant

    cases = [
        {
            'inputs': {'query': '第一题'},
            'label': {'answer': '答案1'},
            'order_no': 0,
            'session_id': 'sess-a',
            'turn_order': 1,
        },
        {
            'inputs': {'query': '第二题'},
            'label': {'answer': '答案2'},
            'order_no': 1,
            'session_id': 'sess-a',
            'turn_order': 2,
        },
        {
            'inputs': {'query': '第三题'},
            'label': {'answer': ''},
        },
    ]
    name = '[No-Set] unit-test'
    created_by = 'ut-user'

    pending_run_id = _insert_agent_evaluation(tenant_id, EvalRunStatus.PENDING)
    evaluation_set_id = materialize_virtual_evaluation_set_for_run(
        tenant_id=tenant_id,
        name=name,
        cases=cases,
        created_by=created_by,
        agent_evaluation_id=pending_run_id,
    )
    assert isinstance(evaluation_set_id, int)
    assert evaluation_set_id > 0

    with get_db_session() as session:
        es = (
            session.query(EvaluationSet)
            .filter(
                EvaluationSet.evaluation_set_id == evaluation_set_id,
                EvaluationSet.tenant_id == tenant_id,
            )
            .one()
        )
        assert es.name == name
        assert es.source_filename == '__no_set_virtual__'
        assert es.case_count == len(cases)
        assert es.generation_status == 'DONE'
        assert es.generation_progress == 100

        case_rows = (
            session.query(EvaluationSetCase)
            .filter(
                EvaluationSetCase.evaluation_set_id == evaluation_set_id,
                EvaluationSetCase.tenant_id == tenant_id,
                EvaluationSetCase.delete_flag == 'N',
            )
            .order_by(EvaluationSetCase.order_no.asc())
            .all()
        )
        assert len(case_rows) == len(cases)
        for index, (case, row) in enumerate(zip(cases, case_rows)):
            assert row.inputs == case['inputs']
            assert row.label == case['label']
            assert row.order_no == int(case.get('order_no', index))
            assert row.session_id == case.get('session_id')
            assert row.turn_order == int(case.get('turn_order', 0))

        run = (
            session.query(AgentEvaluation)
            .filter(
                AgentEvaluation.agent_evaluation_id == pending_run_id,
                AgentEvaluation.tenant_id == tenant_id,
            )
            .one()
        )
        assert run.evaluation_set_id == evaluation_set_id
        assert run.progress_total == len(cases)

    set_count_before, case_count_before = _count_rows(tenant_id)
    with pytest.raises(AppException) as exc_missing:
        materialize_virtual_evaluation_set_for_run(
            tenant_id=tenant_id,
            name=name,
            cases=cases,
            created_by=created_by,
            agent_evaluation_id=absent_numeric_id(__name__),
        )
    assert exc_missing.value.error_code == ErrorCode.COMMON_RESOURCE_NOT_FOUND
    assert str(exc_missing.value) == 'Pending agent evaluation not found'
    assert _count_rows(tenant_id) == (set_count_before, case_count_before)

    for bad_status in (EvalRunStatus.RUNNING, EvalRunStatus.FAILED):
        bad_run_id = _insert_agent_evaluation(tenant_id, bad_status)
        with get_db_session() as session:
            before = (
                session.query(AgentEvaluation)
                .filter(
                    AgentEvaluation.agent_evaluation_id == bad_run_id,
                    AgentEvaluation.tenant_id == tenant_id,
                )
                .one()
            )
            before_status = before.status
            before_set_id = before.evaluation_set_id
            before_progress = before.progress_total

        set_count_before, case_count_before = _count_rows(tenant_id)
        with pytest.raises(AppException) as exc_bad:
            materialize_virtual_evaluation_set_for_run(
                tenant_id=tenant_id,
                name=name,
                cases=cases,
                created_by=created_by,
                agent_evaluation_id=bad_run_id,
            )
        assert exc_bad.value.error_code == ErrorCode.COMMON_RESOURCE_NOT_FOUND
        assert str(exc_bad.value) == 'Pending agent evaluation not found'
        assert _count_rows(tenant_id) == (set_count_before, case_count_before)

        with get_db_session() as session:
            after = (
                session.query(AgentEvaluation)
                .filter(
                    AgentEvaluation.agent_evaluation_id == bad_run_id,
                    AgentEvaluation.tenant_id == tenant_id,
                )
                .one()
            )
            assert after.status == before_status
            assert after.evaluation_set_id == before_set_id
            assert after.progress_total == before_progress
