# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PERSONAL-MGMT-02 preserves public projection and AgentOS scalar composition."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge_collections import KnowledgeCollectionsUsageResult
from nexent.storage.errors import ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_search import knowledge_search_revision
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def management_capacity(mocker):
    from management.services.knowledge_base import (
        personal_capacity_management as module,
    )

    rows = [{'knowledge_id': key, 'tenant_id': 'resource', 'index_name': 'kb-'+str(key), 'knowledge_name': 'Name '+str(key),
        'created_by': user, 'knowledge_sources': 'datamate' if key==3 else 'elasticsearch', 'ingroup_permission': 'PRIVATE',
        'group_ids': None, 'embedding_model_id': None, 'quota_limit_bytes': amount,
        'update_time': date, 'last_doc_update_time': None} for key, user, amount, date in [
            (1, 'one', 3, '2026-01-01T00:00:00Z'), (2, 'one', 4, '2026-02-01T00:00:00Z'),
            (3, 'two', None, '2026-03-01T00:00:00Z')]]
    actor = ServicePrincipal('actual', 'home')
    inputs = {'knowledge_bases': rows, 'source_bytes_by_kb': {1: 5, 2: 7, 3: 11},
        'quotas': {'one': (30, 'individual'), 'two': (40, 'default')}, 'default_quota': 40}
    reader = SimpleNamespace(read_management=Mock(return_value=inputs), authorize_management=Mock())
    display = SimpleNamespace(read=Mock(return_value=({'one': 'z@example.test', 'two': 'a@example.test'},
        {'one': {'cas_username': 'Alpha CAS'}, 'two': {'cas_username': 'Zulu CAS'}})))
    client = SimpleNamespace(knowledge_collection_usage=AsyncMock(return_value=KnowledgeCollectionsUsageResult(items=[
        {'knowledge_id': r['knowledge_id'], 'expected_revision': knowledge_search_revision(r), 'present': True,
            'statistics': {'record_count': key*2, 'source_count': key, 'size_bytes': 1024*key}} for key, r in enumerate(rows, 1)])))

    async def blocking(name, callback, *args, **kwargs):
        assert kwargs.pop('lane') == 'control-io' and kwargs.pop('owner') == 'management.knowledge_base'
        return callback(*args, **kwargs)

    mocker.patch.object(module, 'run_blocking', side_effect=blocking)
    service = module.PersonalCapacityManagement(reader=reader, display=display, client=client)
    return SimpleNamespace(**locals())


async def test_email_sort_and_page_precede_cas_enrichment(management_capacity):
    s = management_capacity
    result = await s.service.read('users', 'resource', s.actor,
        options={'page': 1, 'page_size': 1, 'sort_by': 'user_name', 'sort_order': 'asc'}, context=context())
    assert result['total'] == result['total_pages'] == 2
    item = result['items'][0]
    assert item['user_id'] == 'two' and item['user_name'] == 'a@example.test' and item['cas_username'] == 'Zulu CAS'
    assert item['total_bytes'] == 11 and item['es_physical_bytes'] == 3072 and item['quota_source'] == 'default'
    s.display.read.assert_called_once()
    assert s.display.read.call_args.args[:3] == ('resource', s.actor, ['one', 'two'])
    request, user, tenant = s.client.knowledge_collection_usage.call_args.args
    assert (user, tenant, request.knowledge_ids) == ('actual', 'home', [1, 2, 3])


async def test_keyword_uses_email_not_cas_name(management_capacity):
    s = management_capacity
    result = await s.service.read('users', 'resource', s.actor, options={'keyword': 'Zulu CAS'}, context=context())
    assert result['total'] == 0 and result['items'] == []


async def test_details_preserve_dates_counts_aliases_and_paging(management_capacity):
    s = management_capacity
    result = await s.service.read('details', 'resource', s.actor, subject='one', options={'page_size': 1}, context=context())
    assert result['total'] == 3 and result['total_pages'] == 3
    item = result['kbs'][0]
    assert item['knowledge_id'] == item['kb_id'] == 3 and item['updated_at'] == '2026-03-01T00:00:00Z'
    assert item['doc_count'] == 3 and item['chunk_count'] == 6
    assert item['store_size'] == item['es_physical_size'] == '3.00 KB'
    assert item['store_size_bytes'] == item['es_physical_size_bytes'] == 3072
    assert item['source_size_bytes'] == item['total_size_bytes'] == 11
    assert s.reader.read_management.call_args.kwargs['subject'] == 'one'
    s.display.read.assert_not_called()


async def test_summary_allocation_and_source_are_independent_of_es(management_capacity):
    s = management_capacity
    result = await s.service.read('summary', 'resource', s.actor, context=context())
    assert result == {'user_count': 2, 'kb_count': 3, 'total_bytes': 23, 'total_readable': '23 B',
        'total_es_physical_bytes': 6144, 'total_es_physical_readable': '6.0 KB', 'allocated_quota_bytes': 70,
        'allocated_quota_readable': '70 B', 'default_quota_bytes': 40, 'default_quota_readable': '40 B'}
    s.display.read.assert_not_called()


async def test_publishing_rechecks_current_permission(management_capacity):
    s = management_capacity
    s.reader.authorize_management.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        await s.service.read('summary', 'resource', s.actor, context=context())


async def test_invalid_sort_is_checked_after_live_permission(management_capacity):
    s = management_capacity
    s.reader.read_management.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        await s.service.read('users', 'resource', s.actor, options={'sort_by': 'bad'}, context=context())
    s.client.knowledge_collection_usage.assert_not_awaited()


async def test_historical_alias_summary_counts_once_but_user_rows_count_each(management_capacity):
    s = management_capacity
    s.rows[1]['index_name'] = s.rows[0]['index_name']
    s.client.knowledge_collection_usage.return_value = KnowledgeCollectionsUsageResult(items=[{
        'knowledge_id': r['knowledge_id'], 'expected_revision': knowledge_search_revision(r), 'present': True,
        'statistics': {'record_count': 1, 'source_count': 1, 'size_bytes': 1024}} for r in s.rows[1:]])
    total = await s.service.read('summary', 'resource', s.actor, context=context())
    users = await s.service.read('users', 'resource', s.actor, context=context())
    assert total['total_bytes'] == 18 and sum(row['total_bytes'] for row in users['items']) == 25
    assert total['total_es_physical_bytes'] == 2048
    assert sum(row['es_physical_bytes'] for row in users['items']) == 3072
    assert s.client.knowledge_collection_usage.call_args.args[0].knowledge_ids == [2, 3]


async def test_empty_tenant_has_no_runtime_request_or_display_query(management_capacity):
    s = management_capacity
    s.inputs.update(knowledge_bases=[], source_bytes_by_kb={}, quotas={})
    result = await s.service.read('summary', 'resource', s.actor, context=context())
    assert result['kb_count'] == result['user_count'] == result['total_bytes'] == result['allocated_quota_bytes'] == 0
    s.client.knowledge_collection_usage.assert_not_awaited()
    s.display.read.assert_not_called()


async def test_root_deadline_cancels_work_and_logs_once(management_capacity, mocker, caplog):
    import asyncio

    from management.services.knowledge_base import (
        personal_capacity_management as module,
    )
    from nexent.storage.errors import DeadlineExceeded
    from nexent.storage.models import OperationContext

    saved, exited = [], []

    async def blocked(*args, **kwargs):
        saved.append(kwargs['context'])
        try:
            await asyncio.Event().wait()
        finally:
            exited.append(True)

    mocker.patch.object(module.PersonalCapacityManagement, 'read', new=blocked)
    mocker.patch.object(module, 'OperationContext', side_effect=lambda name, deadline, **kwargs:
        OperationContext(name, module.monotonic() + .02, **kwargs))
    with pytest.raises(DeadlineExceeded):
        await module.personal_capacity_operation('users', 'resource', management_capacity.actor)
    assert exited == [True] and saved[0].cancelled.is_set()
    assert len([r for r in caplog.records if 'personal_capacity_management_timeout' in r.message]) == 1
    assert not [r for r in caplog.records if r.levelname == 'ERROR']
