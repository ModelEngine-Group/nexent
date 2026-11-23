# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DELETE-PUBLIC-03: Northbound owns compatibility without accessing legacy Redis."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.constants import environment
from management.services import northbound as module
from management.services.knowledge_base import deletion
from management.services.knowledge_base.deletion_selection import DocumentLedgerNotFound
from nexent.storage.errors import ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal


@pytest.mark.parametrize('scope,status', [('full', 'success'), ('full', 'pending'), ('source_only', 'success')])
async def test_adapter_keeps_actor_envelope_and_no_tag_cleanup(monkeypatch, scope, status):
    result = {'status': status, 'scope': scope, 'deleted_es_count': 3}
    if status == 'pending':
        result.update(deletion_pending=True, message='Deletion requested; waiting for physical cleanup.')
    invoke = AsyncMock(return_value=result)
    monkeypatch.setattr(module.ElasticSearchService, 'delete_document_by_scope', invoke)
    ctx = SimpleNamespace(user_id='editor', tenant_id='asset-tenant')
    adapted = await module.delete_knowledge_document_for_northbound(
        ctx=ctx, index_name='kb', path_or_url='s3://bucket/key', scope=scope,
    )
    invoke.assert_awaited_once_with('kb', 's3://bucket/key', scope, requested_by='editor', tenant_id='asset-tenant')
    assert adapted['scope'] == scope and adapted['status'] == status and adapted['deleted_es_count'] == 3
    if scope == 'full':
        assert adapted['redis_cleanup']['total_deleted'] == 0
        assert 'Cleaned up 0 Redis records (0 tasks, 0 cache keys).' in adapted['message']
    else:
        assert adapted == result and 'redis_cleanup' not in adapted


async def test_adapter_propagates_resource_denial(monkeypatch):
    invoke = AsyncMock(side_effect=ScopeDenied())
    monkeypatch.setattr(module.ElasticSearchService, 'delete_document_by_scope', invoke)
    with pytest.raises(ScopeDenied):
        await module.delete_knowledge_document_for_northbound(
            ctx=SimpleNamespace(user_id='editor', tenant_id='asset-tenant'), index_name='kb', path_or_url='key', scope='full',
        )
    invoke.assert_awaited_once()


async def test_whole_base_adapter_keeps_actual_scope_and_original_success(monkeypatch):
    expected = {'status': 'success', 'message': 'original result', 'minio_cleanup': {'deleted_count': 2}}
    invoke = AsyncMock(return_value=expected)
    monkeypatch.setattr(module.ElasticSearchService, 'delete_knowledge_base', invoke)
    ctx = SimpleNamespace(user_id='editor', tenant_id='asset-tenant')
    assert await module.delete_knowledge_base_for_northbound(ctx=ctx, index_name='kb') is expected
    invoke.assert_awaited_once_with('kb', requested_by='editor', tenant_id='asset-tenant')


@pytest.mark.parametrize('scope,file_id,enabled,allowed', [
    ('full', None, True, True),
    ('source_only', None, True, False),
    ('full', 'existing-id', True, False),
    ('full', None, False, False),
])
async def test_ledger_miss_uses_source_operation_only_for_enabled_full_path_requests(
    monkeypatch, scope, file_id, enabled, allowed,
):
    monkeypatch.setattr(environment, 'KNOWLEDGE_RUNTIME_HYBRID_ENABLED', enabled)
    coordinator = SimpleNamespace(client=object(), request=AsyncMock(side_effect=DocumentLedgerNotFound()))
    monkeypatch.setattr(deletion, 'default_coordinator', lambda: None)
    monkeypatch.setattr(deletion, 'default_deletion_coordinator', lambda _: coordinator)
    untracked = AsyncMock(return_value={'status': 'success', 'deleted_es_count': 2, 'deleted_minio': False})
    monkeypatch.setattr(deletion, '_delete_untracked_source', untracked)
    delete = deletion.KnowledgeBaseDocumentDeletionService.delete_document_by_scope
    if allowed:
        result = await delete('kb', 'external/path', scope, requested_by='editor', tenant_id='tenant-a')
        assert result['deleted_es_count'] == 2 and not result['deleted_minio']
        untracked.assert_awaited_once_with(coordinator.client, 'kb', 'external/path', ServicePrincipal('editor', 'tenant-a'))
    else:
        with pytest.raises(DocumentLedgerNotFound):
            await delete('kb', 'external/path', scope, requested_by='editor', tenant_id='tenant-a', file_id=file_id)
        untracked.assert_not_awaited()
