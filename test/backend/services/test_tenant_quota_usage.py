# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""QUOTA-USAGE-PUBLIC-01 checks AgentOS-only statistics and shared caching."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from contracts.knowledge_collections import KnowledgeCollectionsUsageResult
from management.services.knowledge_base import usage_cache
from nexent.storage.errors import Conflict, ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_search import knowledge_search_revision
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def usage(mocker):
    from management.services.knowledge_base import quota_usage as module

    usage_cache.invalidate_usage_cache()
    rows = [{'knowledge_id': i, 'index_name': 'kb-' + str(i), 'knowledge_name': 'Name ' + str(i),
                 'tenant_id': 'resource', 'created_by': 'other', 'ingroup_permission': 'PRIVATE',
                 'group_ids': '[]', 'embedding_model_id': None, 'knowledge_sources': 'elasticsearch',
                 'quota_limit_bytes': 10} for i in (1, 2)]
    inputs = {'knowledge_bases': rows, 'source_bytes_by_kb': {1: 8, 2: 12}, 'tenant_source_bytes': 27,
                  'hard_limit_bytes': 20, 'hard_limit_readable': '20 B', 'warning_enabled': False,
                  'warning_threshold_pct': 80, 'critical_threshold_pct': 95,
                  'summary': {'soft_allocated_total_bytes': 20, 'soft_allocated_readable': '20 B',
                               'oversubscription_ratio': 1.0, 'kbs_with_quota': 2}}
    reader = SimpleNamespace(authorize=Mock(return_value=('SU',)), read=Mock(return_value=inputs))

    async def statistics(request, user, tenant):
        return KnowledgeCollectionsUsageResult(items=[{'knowledge_id': i, 'expected_revision': request.expected_revisions[i],
            'present': True, 'statistics': {'record_count': 9, 'size_bytes': 1234, 'source_count': 3}} for i in request.knowledge_ids])

    client = SimpleNamespace(knowledge_collection_usage=AsyncMock(side_effect=statistics))

    async def blocking(name, action, *args, **kwargs):
        assert kwargs.pop('lane') == 'control-io' and kwargs.pop('owner') == 'management.knowledge_base'
        return action(*args, **kwargs)

    mocker.patch.object(module, 'run_blocking', side_effect=blocking)
    service = module.TenantQuotaUsage(reader=reader, client=client)
    actor = ServicePrincipal('actual-user', 'actor-tenant')
    clock = mocker.patch.object(module.time, 'time', return_value=100)
    yield SimpleNamespace(**locals())
    usage_cache.invalidate_usage_cache()
    assert usage_cache._usage_refresh_locks == {}


async def test_usage_preserves_source_authority_and_pinned_actor_scoped_protocol(usage):
    s = usage
    roles, result = await s.service.read('resource', s.actor, detail=True, context=context())
    assert roles == ('SU',) and result['total_bytes'] == 27 and result['usage_pct'] == 135
    assert result['tenant_warning_level'] == 'blocked' and result['available_bytes'] == 0
    assert result['warning_enabled'] is False and result['file_count'] == 6
    # The old provider formats 1234 bytes as 1.21 KB before parsing it for quota display.
    assert result['es_physical_bytes'] == int(1.21 * 1024) * 2
    assert [r['actual_bytes'] for r in result['breakdown']] == [8, 12]
    assert [r['kb_warning_level'] for r in result['breakdown']] == ['warning', 'exceeded']
    call = s.client.knowledge_collection_usage.await_args
    request, user, tenant = call.args
    assert (user, tenant) == ('actual-user', 'actor-tenant') and request.view == 'usage'
    assert request.expected_revisions == {r['knowledge_id']: knowledge_search_revision(r) for r in s.rows}
    assert set(request.model_dump()) == {'knowledge_ids', 'expected_revisions', 'view'}


async def test_cache_ttl_force_refresh_and_current_identity_on_every_hit(usage):
    s = usage
    first = await s.service.read('resource', s.actor, context=context())
    assert 'breakdown' not in first[1]
    s.clock.return_value = 159
    assert len((await s.service.read('resource', s.actor, detail=True, context=context()))[1]['breakdown']) == 2
    assert s.reader.read.call_count == s.client.knowledge_collection_usage.await_count == 1
    assert s.reader.authorize.call_count == 4
    s.clock.return_value = 160
    await s.service.read('resource', s.actor, context=context())
    await s.service.read('resource', s.actor, force_refresh=True, context=context())
    assert s.reader.read.call_count == s.client.knowledge_collection_usage.await_count == 3


async def test_cache_hit_revocation_is_refused_without_runtime_request(usage):
    s = usage
    await s.service.read('resource', s.actor, context=context())
    s.reader.authorize.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        await s.service.read('resource', s.actor, context=context())
    assert s.client.knowledge_collection_usage.await_count == 1


async def test_revocation_after_statistics_prevents_cache_publication(usage):
    s = usage
    s.reader.authorize.side_effect = [('SU',), ScopeDenied()]
    with pytest.raises(ScopeDenied):
        await s.service.read('resource', s.actor, context=context())
    assert 'resource' not in usage_cache._usage_cache


@pytest.mark.parametrize('error', [RuntimeServiceTimeoutError('timeout'), RuntimeError('unavailable')])
async def test_original_optional_observability_failure_keeps_ledger_once(usage, error):
    s = usage
    s.client.knowledge_collection_usage.side_effect = error
    result = (await s.service.read('resource', s.actor, context=context()))[1]
    assert result['total_bytes'] == 27 and result['es_physical_bytes'] == result['file_count'] == 0
    assert s.client.knowledge_collection_usage.await_count == 1


@pytest.mark.parametrize(('status', 'kind'), [(403, ScopeDenied), (409, Conflict)])
async def test_explicit_grant_refusal_never_becomes_zero_success(usage, status, kind):
    s = usage
    s.client.knowledge_collection_usage.side_effect = RuntimeUpstreamError(status, b'refused', {})
    with pytest.raises(kind):
        await s.service.read('resource', s.actor, context=context())
    assert 'resource' not in usage_cache._usage_cache


async def test_statistics_response_must_match_requested_ids_and_revisions(usage):
    s = usage
    s.client.knowledge_collection_usage.side_effect = None
    s.client.knowledge_collection_usage.return_value = KnowledgeCollectionsUsageResult(items=[{
        'knowledge_id': 1, 'expected_revision': '0' * 64, 'present': False}])
    with pytest.raises(Conflict):
        await s.service.read('resource', s.actor, context=context())
    assert 'resource' not in usage_cache._usage_cache


async def test_datamate_skipped_and_statistics_are_batched_at_100(usage):
    s = usage
    s.rows[:] = [dict(s.rows[0], knowledge_id=i, index_name='kb-' + str(i)) for i in range(1, 202)]
    s.rows.append(dict(s.rows[0], knowledge_id=202, index_name='datamate', knowledge_sources='datamate'))
    result = (await s.service.read('resource', s.actor, detail=True, context=context()))[1]
    assert [len(c.args[0].knowledge_ids) for c in s.client.knowledge_collection_usage.await_args_list] == [100, 100, 1]
    assert result['kb_count'] == 202 and result['breakdown'][-1]['file_count'] == 0


async def test_concurrent_cold_requests_compute_once_and_cancellation_releases(usage):
    s = usage
    started, release = asyncio.Event(), asyncio.Event()
    original = s.client.knowledge_collection_usage.side_effect

    async def delayed(*args):
        started.set()
        await release.wait()
        return await original(*args)

    s.client.knowledge_collection_usage.side_effect = delayed
    first = asyncio.create_task(s.service.read('resource', s.actor, context=context()))
    await asyncio.wait_for(started.wait(), 1)
    cancelled = asyncio.create_task(s.service.read('resource', s.actor, context=context()))
    next_request = asyncio.create_task(s.service.read('resource', s.actor, context=context()))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    release.set()
    assert await first == await asyncio.wait_for(next_request, 2)
    assert s.client.knowledge_collection_usage.await_count == s.reader.read.call_count == 1


async def test_missing_and_unavailable_collection_keep_source_bytes(usage):
    s = usage

    async def incomplete(request, *args):
        return KnowledgeCollectionsUsageResult(items=[
            {'knowledge_id': 1, 'expected_revision': request.expected_revisions[1], 'present': False},
            {'knowledge_id': 2, 'expected_revision': request.expected_revisions[2],
             'present': True, 'statistics_error': 'unavailable'},
        ])

    s.client.knowledge_collection_usage.side_effect = incomplete
    result = (await s.service.read('resource', s.actor, detail=True, context=context()))[1]
    assert result['total_bytes'] == 27 and result['file_count'] == result['es_physical_bytes'] == 0
    assert [row['actual_bytes'] for row in result['breakdown']] == [8, 12]


async def test_invalidation_while_runtime_work_runs_prevents_stale_publication(usage):
    s = usage
    original = s.client.knowledge_collection_usage.side_effect

    async def invalidated(*args):
        usage_cache.invalidate_usage_cache('resource')
        return await original(*args)

    s.client.knowledge_collection_usage.side_effect = invalidated
    assert (await s.service.read('resource', s.actor, context=context()))[1]['total_bytes'] == 27
    assert 'resource' not in usage_cache._usage_cache


async def test_parent_deadline_cancels_statistics_and_releases_refresh_permit(usage):
    s = usage
    exited = []

    async def stalled(*args):
        try:
            await asyncio.Event().wait()
        finally:
            exited.append(True)

    s.client.knowledge_collection_usage.side_effect = stalled
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(.02):
            await s.service.read('resource', s.actor, context=context())
    assert exited == [True] and s.client.knowledge_collection_usage.await_count == 1
    assert not usage_cache._usage_refresh_locks and 'resource' not in usage_cache._usage_cache
