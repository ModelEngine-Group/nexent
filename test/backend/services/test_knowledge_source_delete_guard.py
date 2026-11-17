# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DELETE-PUBLIC-02: the public facade must preserve actor and coordinator failures."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from management.services.knowledge_base import deletion as module
from nexent.storage.errors import ScopeDenied, Unavailable

from test.backend.services.test_knowledge_deletion_contract import intent


@pytest.fixture
def facade(monkeypatch):
    row = {'deletion_request': intent().model_dump(mode='json'), 'status': 'DELETED',
           'stage': 'DELETE_DONE', 'deleted_vector_count': 4}
    coordinator = SimpleNamespace(request=AsyncMock(return_value=row))
    shared = Mock()
    monkeypatch.setattr(module, 'default_coordinator', lambda: shared)
    create = Mock(return_value=coordinator)
    monkeypatch.setattr(module, 'default_deletion_coordinator', create)
    return coordinator, shared, create


async def test_current_actor_and_authoritative_file_id_reach_the_persistent_owner(facade):
    coordinator, shared, create = facade
    result = await module.KnowledgeBaseDocumentDeletionService.delete_document_by_scope(
        'kb', 'untrusted-alias', 'full', file_id='b' * 32, requested_by='editor',
        tenant_id='tenant', remove_tags=True,
    )
    assert result['deleted_es_count'] == 4 and result['lifecycle_deleted']
    create.assert_called_once_with(shared)
    args, kwargs = coordinator.request.call_args
    assert args[:3] == ('kb', 'untrusted-alias', 'full')
    assert args[3].user_id == 'editor' and args[3].tenant_id == 'tenant'
    assert kwargs == {'file_id': 'b' * 32, 'remove_tags': True}


@pytest.mark.parametrize('error', [Unavailable(), ScopeDenied(), ValueError('invalid scope')])
async def test_selection_or_storage_failure_propagates_without_a_legacy_fallback(facade, error):
    coordinator, _, _ = facade
    coordinator.request.side_effect = error
    with pytest.raises(type(error)):
        await module.KnowledgeBaseDocumentDeletionService.delete_document_by_scope(
            'kb', 'key', 'source_only', requested_by='editor', tenant_id='tenant',
        )
    coordinator.request.assert_awaited_once()
