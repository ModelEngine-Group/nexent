from __future__ import annotations

import uuid

import pytest

from database.client import as_dict, get_db_session
from database.db_models import AgentEvaluation, EvaluationSet, EvaluationSetCase
from database.evaluation_set_db import cleanup_orphaned_virtual_evaluation_sets


NO_SET_MARKER = '__no_set_virtual__'


def _make_tenant() -> str:
    return f'd5_orphan_{uuid.uuid4().hex[:16]}'


def _add_set(session, tenant_id: str, name: str, source_filename: str | None, delete_flag: str) -> int:
    rec = EvaluationSet(
        tenant_id=tenant_id,
        name=name,
        source_filename=source_filename,
        delete_flag=delete_flag,
    )
    session.add(rec)
    session.flush()
    return int(rec.evaluation_set_id)


def _add_case(session, tenant_id: str, evaluation_set_id: int, case_id: str, order_no: int) -> None:
    session.add(
        EvaluationSetCase(
            tenant_id=tenant_id,
            evaluation_set_id=evaluation_set_id,
            case_id=case_id,
            inputs={'query': f'{case_id}-query'},
            label={'answer': f'{case_id}-answer'},
            order_no=order_no,
            delete_flag='N',
        )
    )


def _snapshot(tenant_id: str, set_ids: list[int]) -> dict:
    with get_db_session() as session:
        result: dict = {}
        for sid in set_ids:
            rec = (
                session.query(EvaluationSet)
                .filter(
                    EvaluationSet.tenant_id == tenant_id,
                    EvaluationSet.evaluation_set_id == sid,
                )
                .first()
            )
            result[f'set_{sid}'] = as_dict(rec) if rec is not None else None
            rows = (
                session.query(EvaluationSetCase)
                .filter(
                    EvaluationSetCase.tenant_id == tenant_id,
                    EvaluationSetCase.evaluation_set_id == sid,
                )
                .order_by(EvaluationSetCase.order_no, EvaluationSetCase.evaluation_set_case_id)
                .all()
            )
            result[f'cases_{sid}'] = [as_dict(row) for row in rows]
        return result


def _count(tenant_id: str, evaluation_set_id: int) -> tuple[int, int]:
    with get_db_session() as session:
        set_count = (
            session.query(EvaluationSet)
            .filter(
                EvaluationSet.tenant_id == tenant_id,
                EvaluationSet.evaluation_set_id == evaluation_set_id,
            )
            .count()
        )
        case_count = (
            session.query(EvaluationSetCase)
            .filter(
                EvaluationSetCase.tenant_id == tenant_id,
                EvaluationSetCase.evaluation_set_id == evaluation_set_id,
            )
            .count()
        )
        return set_count, case_count


def _cleanup_tenant(tenant_id: str) -> None:
    with get_db_session() as session:
        session.query(AgentEvaluation).filter(
            AgentEvaluation.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        session.query(EvaluationSetCase).filter(
            EvaluationSetCase.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        session.query(EvaluationSet).filter(
            EvaluationSet.tenant_id == tenant_id
        ).delete(synchronize_session=False)


@pytest.mark.stage('D5')
@pytest.mark.case_id('REL-AUTO-0ED11882BC558420')
def test_cleanup_orphaned_virtual_evaluation_sets():
    tenant_id = _make_tenant()
    try:
        with get_db_session() as session:
            s1_id = _add_set(session, tenant_id, f'{tenant_id}-s1', NO_SET_MARKER, 'N')
            _add_case(session, tenant_id, s1_id, f'{tenant_id}-s1-c1', 0)
            _add_case(session, tenant_id, s1_id, f'{tenant_id}-s1-c2', 1)

            s2_id = _add_set(session, tenant_id, f'{tenant_id}-s2', NO_SET_MARKER, 'N')
            _add_case(session, tenant_id, s2_id, f'{tenant_id}-s2-c1', 0)
            _add_case(session, tenant_id, s2_id, f'{tenant_id}-s2-c2', 1)
            session.add(
                AgentEvaluation(
                    tenant_id=tenant_id,
                    agent_id=1,
                    agent_version_no=1,
                    evaluation_set_id=s2_id,
                    status='PENDING',
                    delete_flag='N',
                )
            )

            s3_id = _add_set(session, tenant_id, f'{tenant_id}-s3', 'normal_source.json', 'N')
            _add_case(session, tenant_id, s3_id, f'{tenant_id}-s3-c1', 0)

            s4_id = _add_set(session, tenant_id, f'{tenant_id}-s4', NO_SET_MARKER, 'Y')
            _add_case(session, tenant_id, s4_id, f'{tenant_id}-s4-c1', 0)

        baseline = _snapshot(tenant_id, [s2_id, s3_id, s4_id])
        assert baseline[f'set_{s2_id}'] is not None
        assert baseline[f'set_{s3_id}'] is not None
        assert baseline[f'set_{s4_id}'] is not None

        removed = cleanup_orphaned_virtual_evaluation_sets()
        assert removed == 1
        assert _count(tenant_id, s1_id) == (0, 0)
        assert _snapshot(tenant_id, [s2_id, s3_id, s4_id]) == baseline

        removed_again = cleanup_orphaned_virtual_evaluation_sets()
        assert removed_again == 0
        assert _snapshot(tenant_id, [s2_id, s3_id, s4_id]) == baseline
    finally:
        _cleanup_tenant(tenant_id)
