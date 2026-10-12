from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

import pytest

from consts.evaluation_status import EvalRunStatus
from database.agent_evaluation_db import (
    claim_agent_evaluation_run,
    list_dispatchable_pending_runs,
)
from database.client import get_db_session
from database.db_models import AgentEvaluation
from services import evaluation_maintenance
from services import runtime_proxy_service


def _insert_run(session, *, tenant_id, created_by, evaluation_set_id, status, delete_flag, create_time):
    rec = AgentEvaluation(
        tenant_id=tenant_id,
        agent_id=1,
        agent_version_no=1,
        evaluation_set_id=evaluation_set_id,
        status=status,
        progress_total=1,
        progress_done=0,
        judge_model_id=None,
        created_by=created_by,
        updated_by=created_by,
        create_time=create_time,
        update_time=create_time,
        delete_flag=delete_flag,
    )
    session.add(rec)
    session.flush()
    return rec.agent_evaluation_id


@pytest.mark.case_id('REL-AUTO-CCF3D3CB5D0FC268')
@pytest.mark.stage('D5')
def test_persistent_pending_redispatch_and_idempotent_claim(monkeypatch, caplog):
    tenant = f'rel-auto-ccf3d3cb5d0fc268-{uuid.uuid4().hex[:12]}'
    base = datetime(2024, 1, 1, 0, 0, 0)

    row_specs = [
        ('good_a', tenant, 'usr-a', 1001, 'PENDING', 'N', base),
        ('good_b', tenant, 'usr-b', 1002, 'PENDING', 'N', base + timedelta(seconds=1)),
        ('no_tenant', '', 'usr-c', 1003, 'PENDING', 'N', base + timedelta(seconds=2)),
        ('no_creator', tenant, None, 1004, 'PENDING', 'N', base + timedelta(seconds=3)),
        ('no_set', tenant, 'usr-d', 0, 'PENDING', 'N', base + timedelta(seconds=4)),
        ('deleted', tenant, 'usr-e', 1005, 'PENDING', 'Y', base + timedelta(seconds=5)),
        ('running', tenant, 'usr-f', 1006, 'RUNNING', 'N', base + timedelta(seconds=6)),
    ]

    ids = {}
    created_ids = []
    with get_db_session() as session:
        for name, tid, uid, es_id, status, dflag, ctime in row_specs:
            eid = _insert_run(
                session,
                tenant_id=tid,
                created_by=uid,
                evaluation_set_id=es_id,
                status=status,
                delete_flag=dflag,
                create_time=ctime,
            )
            ids[name] = eid
            created_ids.append(eid)

    try:
        runs = list_dispatchable_pending_runs()
        result_ids = [r['agent_evaluation_id'] for r in runs]

        for name in ('no_set', 'deleted', 'running'):
            assert ids[name] not in result_ids, f'{name} must be excluded'
        for name in ('good_a', 'good_b', 'no_tenant', 'no_creator'):
            assert ids[name] in result_ids, f'{name} must be returned'

        times = [r['create_time'] for r in runs]
        assert times == sorted(times), 'list_dispatchable_pending_runs must order by create_time ASC'
        positions = [
            result_ids.index(ids[name])
            for name in ('good_a', 'good_b', 'no_tenant', 'no_creator')
        ]
        assert positions == sorted(positions), 'my dispatchable rows must keep create_time order'

        calls = []

        def recording_dispatch(agent_evaluation_id, user_id, tenant_id):
            calls.append((agent_evaluation_id, user_id, tenant_id))
            return {'accepted': True}

        monkeypatch.setattr(runtime_proxy_service, 'dispatch_agent_evaluation_run', recording_dispatch)
        with caplog.at_level(logging.WARNING):
            evaluation_maintenance._dispatch_pending_runs(runs)

        my_calls = [c for c in calls if c[2] == tenant]
        by_id = {c[0]: c for c in my_calls}
        assert sorted(by_id) == sorted([ids['good_a'], ids['good_b']]), 'only complete runs are dispatched'
        assert by_id[ids['good_a']][1] == 'usr-a'
        assert by_id[ids['good_b']][1] == 'usr-b'
        for eid in (ids['good_a'], ids['good_b']):
            assert isinstance(eid, int)
            assert isinstance(by_id[eid][1], str)
            assert isinstance(by_id[eid][2], str)
        assert ids['no_tenant'] not in by_id
        assert ids['no_creator'] not in by_id

        log_text = caplog.text
        assert 'Cannot redispatch pending evaluation' in log_text
        assert str(ids['no_tenant']) in log_text
        assert str(ids['no_creator']) in log_text

        def raising_dispatch(agent_evaluation_id, user_id, tenant_id):
            raise RuntimeError('runtime unavailable')

        monkeypatch.setattr(runtime_proxy_service, 'dispatch_agent_evaluation_run', raising_dispatch)
        retryable = [r for r in runs if r['agent_evaluation_id'] in (ids['good_a'], ids['good_b'])]
        evaluation_maintenance._dispatch_pending_runs(retryable)

        with get_db_session() as session:
            for name in ('good_a', 'good_b'):
                rec = (
                    session.query(AgentEvaluation)
                    .filter(AgentEvaluation.agent_evaluation_id == ids[name])
                    .first()
                )
                assert rec is not None
                assert rec.status == EvalRunStatus.PENDING, f'{name} must stay PENDING after dispatch failure'

        next_ids = [r['agent_evaluation_id'] for r in list_dispatchable_pending_runs()]
        assert ids['good_a'] in next_ids and ids['good_b'] in next_ids

        first = claim_agent_evaluation_run(agent_evaluation_id=ids['good_b'], tenant_id=tenant, updated_by='usr-b')
        assert first is True
        with get_db_session() as session:
            rec = (
                session.query(AgentEvaluation)
                .filter(AgentEvaluation.agent_evaluation_id == ids['good_b'])
                .first()
            )
            assert rec.status == EvalRunStatus.RUNNING
        second = claim_agent_evaluation_run(agent_evaluation_id=ids['good_b'], tenant_id=tenant, updated_by='usr-b')
        assert second is False

    finally:
        with get_db_session() as session:
            if created_ids:
                session.query(AgentEvaluation).filter(
                    AgentEvaluation.agent_evaluation_id.in_(created_ids)
                ).delete(synchronize_session=False)
