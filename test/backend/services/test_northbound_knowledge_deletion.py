# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DELETE-PUBLIC-03: Northbound owns compatibility without accessing legacy Redis."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from management.services import northbound as module
from nexent.storage.errors import ScopeDenied


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
