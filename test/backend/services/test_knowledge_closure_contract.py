# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Missing closure evidence is unknown; truthy strings are never trusted."""

import pytest
from contracts.agentos_knowledge import KnowledgeJobState
from contracts.knowledge_cleanse import KnowledgeCleanseState, cleanse_state
from pydantic import ValidationError


@pytest.mark.parametrize('schema,flag', [(KnowledgeJobState, 'writer_ended'),
                                       (KnowledgeCleanseState, 'execution_ended')])
@pytest.mark.parametrize('value', [1, 'true'])
def test_closure_flags_are_strict_booleans(schema, flag, value):
    with pytest.raises(ValidationError):
        schema(knowledge_id=1, file_id='a' * 32, file_version=0, job_id='b' * 32, status='failed', **{flag: value})


def test_cleanse_closure_is_taken_from_actual_persisted_record():
    state = cleanse_state({'scope_kind': 'knowledge', 'knowledge_id': 1, 'file_id': 'a' * 32, 'file_version': 0,
        'job_id': 'b' * 32, 'status': 'failed', 'error_code': None, 'artifact': None,
        'execution_ended': True, 'reconcile_required': False})
    assert state.execution_ended is True and state.reconcile_required is False


@pytest.mark.parametrize('schema', [KnowledgeJobState, KnowledgeCleanseState])
def test_older_response_without_closure_does_not_imply_it_is_settled(schema):
    state = schema(knowledge_id=1, file_id='a' * 32, file_version=0, job_id='b' * 32, status='failed')
    assert state.reconcile_required is None


def test_executed_historical_cleanse_without_private_directory_has_unknown_ownership():
    state = cleanse_state({'scope_kind': 'knowledge', 'knowledge_id': 1, 'file_id': 'a' * 32, 'file_version': 0,
        'job_id': 'b' * 32, 'status': 'failed', 'error_code': None, 'artifact': None,
        'execution_ended': True, 'reconcile_required': False, 'attempt_id': 'c' * 32, 'owner_id': 'worker',
        'artifact_prefix': None})
    assert state.artifact_ownership_known is False
