# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public chunk browsing preserves pagination while using only AgentOS for content."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.agentos_knowledge import KnowledgeChunksGrant, KnowledgeChunksResult
from management.services.knowledge_base.chunk_browser import KnowledgeChunkBrowser
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def browser():
    grant = KnowledgeChunksGrant(knowledge_id=1, collection='kb', resource_tenant_id='tenant', revision='a' * 64)
    files = [{'file_id': 'c' * 32, 'knowledge_id': 1, 'tenant_id': 'tenant', 'object_name': 'knowledge/a.txt',
              'local_source_path': None, 'delete_flag': 'N', 'original_filename': 'a.txt', 'create_time': '2026-11-18T00:00:00Z'}]
    client = SimpleNamespace(knowledge_chunks=AsyncMock())
    service = KnowledgeChunkBrowser(client=client)
    service._snapshot = AsyncMock(return_value=(grant, files))
    def page(offset, count, total, next_offset):
        return KnowledgeChunksResult(knowledge_id=1, knowledge_revision=grant.revision, data_revision='b' * 64,
            total=total, next_offset=next_offset, chunks=[{'knowledge_id': 1, 'file_id': 'c' * 32, 'file_version': 0,
                'chunk_id': f'chunk-{i}', 'chunk_index': i, 'filename': 'a.txt', 'content': f'content-{i}',
                'location': {'language': 'zh', 'extra': 'private'}} for i in range(offset, offset+count)])
    client.knowledge_chunks.return_value = page(0, 2, 2, None)
    return SimpleNamespace(service=service, client=client, files=files, grant=grant,
                           actor=ServicePrincipal('reader', 'tenant'), page=page)


async def test_all_chunks_keep_public_fields_and_actual_identity(browser):
    s = browser
    result = await s.service.browse('kb', s.actor)
    assert result['status'] == 'success' and result['total'] == 2
    assert result['page'] is None and result['page_size'] is None
    assert result['chunks'][0] == {'id': 'chunk-0', 'filename': 'a.txt', 'content': 'content-0',
        'path_or_url': 'knowledge/a.txt', 'create_time': '2026-11-18T00:00:00Z', 'language': 'zh'}
    request, user, tenant = s.client.knowledge_chunks.call_args.args
    assert user == 'reader' and tenant == 'tenant' and request.file_ids is None
    assert s.service._snapshot.await_count == 2


async def test_standalone_public_chunk_keeps_null_filename_and_original_path(browser):
    s = browser
    s.client.knowledge_chunks.return_value = KnowledgeChunksResult(knowledge_id=1,
        knowledge_revision=s.grant.revision, data_revision='b'*64, total=1, chunks=[{
            'knowledge_id': 1, 'chunk_id': 'manual', 'content': 'plain', 'filename': None,
            'location': {'path_or_url': 'manual/source', 'create_time': 'original-time'},
        }])
    result = await s.service.browse('kb', s.actor, path_or_url='manual/source')
    assert result['chunks'] == [{'id': 'manual', 'content': 'plain', 'filename': None,
        'path_or_url': 'manual/source', 'create_time': 'original-time'}]
    request = s.client.knowledge_chunks.call_args.args[0]
    assert request.file_ids == [] and request.standalone_path == 'manual/source'


async def test_file_source_override_can_match_outside_default_file_path(browser):
    from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
    s = browser
    result = s.page(0, 1, 1, None)
    result.chunks[0].location = {PUBLIC_CHUNK_SOURCE_KEY: {'id': 'alias', 'path_or_url': ['manual/source']}}
    s.client.knowledge_chunks.return_value = result
    response = await s.service.browse('kb', s.actor, path_or_url='manual/source')
    assert response['chunks'][0]['path_or_url'] == ['manual/source']
    assert s.client.knowledge_chunks.await_args.args[0].file_ids == []
    with pytest.raises(Conflict):
        await s.service.browse('kb', s.actor, path_or_url='knowledge/a.txt')


async def test_public_pagination_keeps_original_page_values_and_clamps_query(browser):
    s = browser
    s.client.knowledge_chunks.return_value = s.page(0, 1, 2, 1)
    result = await s.service.browse('kb', s.actor, page=0, page_size=-2)
    assert result['page'] == 0 and result['page_size'] == -2 and len(result['chunks']) == 1
    request = s.client.knowledge_chunks.call_args.args[0]
    assert request.offset == 0 and request.limit == 1


async def test_large_page_freezes_revision_across_internal_windows(browser):
    s = browser
    s.client.knowledge_chunks.side_effect = [s.page(0, 1000, 1002, 1000), s.page(1000, 2, 1002, None)]
    result = await s.service.browse('kb', s.actor, page=1, page_size=1002)
    assert len(result['chunks']) == 1002 and result['total'] == 1002
    first, second = [call.args[0] for call in s.client.knowledge_chunks.call_args_list]
    assert first.expected_data_revision is None and second.expected_data_revision == 'b' * 64
    assert second.offset == 1000 and second.limit == 2


async def test_path_filter_uses_source_identity_and_missing_path_is_empty(browser):
    s = browser
    await s.service.browse('kb', s.actor, path_or_url='knowledge/a.txt')
    assert s.client.knowledge_chunks.call_args.args[0].file_ids == ['c' * 32]
    s.client.knowledge_chunks.return_value = s.page(0, 0, 0, None)
    await s.service.browse('kb', s.actor, path_or_url='a.txt')
    assert s.client.knowledge_chunks.call_args.args[0].file_ids == []


@pytest.mark.parametrize('change', ['revision', 'files', 'foreign_file', 'foreign_standalone', 'incomplete'])
async def test_inconsistent_content_or_authority_never_returns_partial_success(browser, change):
    s = browser
    if change == 'revision':
        s.service._snapshot.side_effect = [(s.grant, s.files), (s.grant.model_copy(update={'revision': 'f' * 64}), s.files)]
    elif change == 'files':
        s.service._snapshot.side_effect = [(s.grant, s.files), (s.grant, [])]
    elif change == 'foreign_file':
        s.client.knowledge_chunks.return_value.chunks[0].file_id = 'd' * 32
    elif change == 'foreign_standalone':
        s.client.knowledge_chunks.return_value.chunks[0] = s.client.knowledge_chunks.return_value.chunks[0].model_copy(
            update={'knowledge_id': 2, 'file_id': None, 'file_version': None, 'chunk_index': None})
    else:
        s.client.knowledge_chunks.return_value.chunks.pop()
    with pytest.raises((Conflict, ScopeDenied)):
        await s.service.browse('kb', s.actor)


async def test_total_timeout_cancels_request_without_retry(browser):
    s = browser
    ended = []
    async def stalled(*args):
        try:
            await asyncio.Event().wait()
        finally:
            ended.append(True)
    s.client.knowledge_chunks.side_effect = stalled
    s.service.operation_seconds = 0.02
    with pytest.raises(DeadlineExceeded):
        await s.service.browse('kb', s.actor)
    assert ended == [True] and s.client.knowledge_chunks.await_count == 1
