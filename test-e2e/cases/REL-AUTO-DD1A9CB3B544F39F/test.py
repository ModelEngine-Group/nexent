from __future__ import annotations

import contextlib
import hashlib
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database.evaluation_set_db as evaluation_set_db
from database.db_models import EvaluationSet, EvaluationSetCase
from shared.postgres import postgres_sql, postgres_url


def _noop_with_for_update(self, *args, **kwargs):
    return self


def _case_ids(session_factory, set_id):
    session = session_factory()
    try:
        rows = (
            session.query(EvaluationSetCase.evaluation_set_case_id)
            .filter(EvaluationSetCase.evaluation_set_id == set_id)
            .order_by(EvaluationSetCase.evaluation_set_case_id.asc())
            .all()
        )
        return [row[0] for row in rows]
    finally:
        session.close()


def _set_state(session_factory, set_id):
    session = session_factory()
    try:
        row = (
            session.query(EvaluationSet)
            .filter(EvaluationSet.evaluation_set_id == set_id)
            .first()
        )
        if row is None:
            return None
        return row.generation_status, row.generation_progress, row.delete_flag
    finally:
        session.close()


def _seed(
    session_factory,
    set_id,
    tenant,
    status,
    progress,
    case_count,
    case_ids,
    delete_flag='N',
):
    session = session_factory()
    try:
        session.add(
            EvaluationSet(
                evaluation_set_id=set_id,
                tenant_id=tenant,
                name=f'rec-set-{set_id}',
                case_count=case_count,
                generation_status=status,
                generation_progress=progress,
                delete_flag=delete_flag,
            )
        )
        for case_id in case_ids:
            session.add(
                EvaluationSetCase(
                    evaluation_set_case_id=case_id,
                    tenant_id=tenant,
                    evaluation_set_id=set_id,
                    case_id=f'case-{case_id}',
                    inputs={'query': f'query-{case_id}'},
                    label={'answer': f'answer-{case_id}'},
                    order_no=case_id,
                    delete_flag='N',
                )
            )
        session.commit()
    finally:
        session.close()


@pytest.fixture
def recover_env(monkeypatch):
    batch = os.environ.get('TEST_BATCH', 'manual')
    schema = 'nexent_test_' + hashlib.sha256(batch.encode()).hexdigest()[:12]
    postgres_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}";')
    original_set_schema = EvaluationSet.__table__.schema
    original_case_schema = EvaluationSetCase.__table__.schema
    monkeypatch.setattr(EvaluationSet.__table__, 'schema', schema)
    monkeypatch.setattr(EvaluationSetCase.__table__, 'schema', schema)
    engine = create_engine(postgres_url())
    EvaluationSet.__table__.create(engine, checkfirst=True)
    EvaluationSetCase.__table__.create(engine, checkfirst=True)
    session_factory = sessionmaker(bind=engine)

    @contextlib.contextmanager
    def _session():
        session = session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(evaluation_set_db, 'get_db_session', _session)
    # Real PostgreSQL supports row locking; do not suppress the product lock.
    try:
        yield session_factory
    finally:
        engine.dispose()
        monkeypatch.setattr(EvaluationSet.__table__, 'schema', original_set_schema)
        monkeypatch.setattr(EvaluationSetCase.__table__, 'schema', original_case_schema)
        postgres_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')


@pytest.mark.stage('D5')
@pytest.mark.case_id('REL-AUTO-DD1A9CB3B544F39F')
def test_recover_interrupted_generations(recover_env):
    session_factory = recover_env
    tenant = 'tenant-recover-interrupted-test'

    _seed(session_factory, 1, tenant, 'GENERATING', 42, 3, [1, 2, 3, 4])
    _seed(session_factory, 2, tenant, 'GENERATING', 55, 3, [11, 12, 13, 14, 15])
    _seed(session_factory, 3, tenant, 'GENERATING', 77, 0, [21, 22, 23])
    _seed(session_factory, 4, tenant, 'DONE', 100, 1, [31, 32])
    _seed(session_factory, 5, tenant, 'GENERATING', 33, 2, [41, 42], delete_flag='Y')

    processed = evaluation_set_db.recover_interrupted_generations()
    assert processed == 3

    assert _set_state(session_factory, 1) == ('FAILED', 0, 'N')
    assert _case_ids(session_factory, 1) == [1, 2, 3]

    assert _set_state(session_factory, 2) == ('FAILED', 0, 'N')
    assert _case_ids(session_factory, 2) == [11, 12, 13]

    assert _set_state(session_factory, 3) == ('FAILED', 0, 'N')
    assert _case_ids(session_factory, 3) == []

    assert _set_state(session_factory, 4) == ('DONE', 100, 'N')
    assert _case_ids(session_factory, 4) == [31, 32]

    assert _set_state(session_factory, 5) == ('GENERATING', 33, 'Y')
    assert _case_ids(session_factory, 5) == [41, 42]

    assert evaluation_set_db.recover_interrupted_generations() == 0

    assert _set_state(session_factory, 1) == ('FAILED', 0, 'N')
    assert _case_ids(session_factory, 1) == [1, 2, 3]
    assert _case_ids(session_factory, 3) == []
    assert _set_state(session_factory, 4) == ('DONE', 100, 'N')
    assert _case_ids(session_factory, 5) == [41, 42]
