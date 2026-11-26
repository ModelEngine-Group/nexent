# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql

from management.db import runtime_recovery as repository


@pytest.fixture
def session(monkeypatch):
    current = Mock()
    current.execute.return_value.rowcount = 1

    @contextmanager
    def scope():
        yield current

    monkeypatch.setattr(repository, 'get_db_session', scope)
    return current


def statements(session):
    return [call.args[0].compile(dialect=postgresql.dialect()) for call in session.execute.call_args_list]


@pytest.mark.parametrize('associations', [{}, {'evaluation_id': 12}, {'assistant_message_id': True},
                                        {'automation_run_id': 'invalid'}, {'evaluation_id': 2**64}])
def test_missing_or_corrupt_associations_do_not_broaden_recovery(session, associations):
    result = repository.fail_exact_owned_work(tenant_id='tenant', user_id='user', conversation_id=1, **associations)
    assert not any(result.values())
    session.execute.assert_not_called()


def test_message_recovery_is_exact_owner_conversation_and_streaming_status(session):
    result = repository.fail_exact_owned_work(tenant_id='tenant', user_id='user', conversation_id=8,
                                               assistant_message_id=42)
    compiled = statements(session)[0]
    assert compiled.params['message_id_1'] == 42
    assert compiled.params['conversation_id_1'] == 8
    assert compiled.params['created_by_1'] == 'user'
    assert compiled.params['status_1'] == 'streaming'
    assert compiled.params['message_role_1'] == 'assistant'
    assert compiled.params['delete_flag_1'] == 'N'
    assert result['conversation_messages'] == 1
    session.commit.assert_not_called()


def test_child_case_recovery_does_not_fail_the_whole_parent(session):
    result = repository.fail_exact_owned_work(tenant_id='tenant', user_id='user', conversation_id=-1,
                                               evaluation_id=21, evaluation_case_id=22)
    compiled = statements(session)
    assert len(compiled) == 1 and str(compiled[0]).startswith('UPDATE nexent.agent_evaluation_case_t')
    assert compiled[0].params['agent_evaluation_case_id_1'] == 22
    assert compiled[0].params['agent_evaluation_id_1'] == 21
    assert compiled[0].params['tenant_id_1'] == 'tenant'
    assert result['agent_evaluations'] == 0 and result['evaluation_cases'] == 1


def test_batch_recovery_updates_only_cases_of_the_proved_parent(session):
    result = repository.fail_exact_owned_work(tenant_id='tenant', user_id='user', conversation_id='evaluation:21',
                                               evaluation_id=21, evaluation_batch=True)
    compiled = statements(session)
    assert len(compiled) == 2
    assert all(item.params['agent_evaluation_id_1'] == 21 and item.params['tenant_id_1'] == 'tenant'
               for item in compiled)
    assert result['agent_evaluations'] == 1
    with pytest.raises(ValueError):
        repository.fail_exact_owned_work(tenant_id='tenant', user_id='user', conversation_id='evaluation:21',
                                        evaluation_id=21, evaluation_case_id=22, evaluation_batch=True)


def test_automation_lock_release_requires_exact_task_and_lock_owner(session):
    result = repository.fail_exact_owned_work(tenant_id='tenant', user_id='user', conversation_id=8,
                                               automation_run_id=31, automation_task_id=32,
                                               automation_lock_owner='old-scheduler')
    run, task = statements(session)
    assert run.params['run_id_1'] == 31 and run.params['task_id_1'] == 32
    assert run.params['status_1'] == 'RUNNING'
    assert task.params['task_id_1'] == 32 and task.params['lock_owner_1'] == 'old-scheduler'
    assert task.params['tenant_id_1'] == 'tenant' and task.params['user_id_1'] == 'user'
    assert 'EXISTS' in str(task) and task.params['run_id_1'] == 31
    assert result['automation_locks'] == 1


def test_no_automation_lock_owner_never_releases_any_task_lock(session):
    repository.fail_exact_owned_work(tenant_id='tenant', user_id='user', conversation_id=8,
                                     automation_run_id=31, automation_task_id=32)
    assert len(statements(session)) == 1


def test_unstarted_claim_compensation_checks_original_timestamp_and_actor(session):
    observed = datetime.now(timezone.utc)
    session.execute.return_value.first.return_value = (observed,)
    assert repository.claim_owned_evaluation_run(21, 'tenant', 'user') is observed
    assert repository.restore_unstarted_evaluation_run(21, 'tenant', 'user', observed)
    claim, restore = statements(session)
    assert 'RETURNING' in str(claim)
    assert restore.params['agent_evaluation_id_1'] == 21 and restore.params['updated_by_1'] == 'user'
    assert restore.params['update_time_1'] == observed
    assert restore.params['status_1'] == 'RUNNING'
    session.commit.assert_not_called()


def test_database_failure_propagates_for_conservative_reconciliation(session):
    session.execute.side_effect = RuntimeError('database unavailable')
    with pytest.raises(RuntimeError, match='database unavailable'):
        repository.fail_exact_owned_work(tenant_id='tenant', user_id='user', conversation_id=8,
                                         assistant_message_id=42)
