# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Delegated file status inspection grants no content or new execution authority."""

from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import KnowledgeAuthorizationRequest, ObjectReference
from contracts.knowledge_admission import (
    KnowledgeBaseDeletionIntent,
    KnowledgeOwnerCleanup,
)
from contracts.knowledge_deletion import KnowledgeDeletionIntent
from management.services.knowledge_base.authorization import KnowledgeAuthorization
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_cleanse_jobs import knowledge_request


@pytest.fixture
def delegated(resources):  # noqa: F811
    _, update, engine, tables = resources
    source = knowledge_request().source
    parent = KnowledgeBaseDeletionIntent(knowledge_id=1, index_name='kb-one', user_id='admin',
        owner_cleanup=KnowledgeOwnerCleanup(purpose='user_deletion', owner_user_id='owner', actor_tenant_id='operator'))
    intent = KnowledgeDeletionIntent(knowledge_id=1, file_id='b' * 32, file_version=0, user_id='admin', scope='full',
                                     index_name='kb-one', filename='source.txt', object_name=source.key, source=source)
    update('cleanse_knowledge', created_by='owner', ingroup_permission='PRIVATE', deletion_request=parent.model_dump(mode='json'))
    update('cleanse_files', status='DELETE_REQUESTED', stage='DELETE_RUNTIME_PENDING', object_name=source.key,
           deletion_request=intent.model_dump(mode='json'))
    update('cleanse_memberships', delete_flag='Y')
    records = bind_cleanse_resources(StorageScope('management', 'tenant-a', 'admin', set(tables)), engine)
    jobs = Mock()
    try:
        yield KnowledgeAuthorization(jobs, records, user_id='admin'), intent, update, jobs
    finally:
        records.close()


@pytest.mark.parametrize('action', ['delete', 'inspect'])
def test_scoped_delete_and_its_status_inspection_survive_owner_revocation(delegated, action):
    policy, intent, _, jobs = delegated
    request = KnowledgeAuthorizationRequest(knowledge_id=1, file_id=intent.file_id, file_version=0, action=action)
    grant = policy.authorize(request, context=context())
    assert grant.action == action and grant.source is None and grant.collection == 'kb-one'
    jobs.query.assert_not_called()


@pytest.mark.parametrize('action', ['upload', 'execute'])
def test_deprovision_never_authorizes_new_execution(delegated, action):
    policy, intent, _, jobs = delegated
    request = KnowledgeAuthorizationRequest(knowledge_id=1, file_id=intent.file_id, file_version=0, action=action,
        artifact=ObjectReference(space='files', key='artifacts/source/artifact.json', version='etag:v1', sha256='a' * 64), parser_version='v2')
    with pytest.raises(ScopeDenied):
        policy.authorize(request, context=context())
    jobs.query.assert_not_called()


@pytest.mark.parametrize('change', [{'user_id': 'owner'}, {'scope': 'source_only'}, {'file_version': 1}, {'file_id': 'c' * 32}])
def test_cleanup_status_requires_the_exact_full_deletion_intent(delegated, change):
    policy, intent, update, _ = delegated
    update('cleanse_files', deletion_request={**intent.model_dump(mode='json'), **change})
    request = KnowledgeAuthorizationRequest(knowledge_id=1, file_id=intent.file_id, file_version=0, action='inspect')
    with pytest.raises(ScopeDenied):
        policy.authorize(request, context=context())
