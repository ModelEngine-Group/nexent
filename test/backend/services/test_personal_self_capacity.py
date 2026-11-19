# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PERSONAL-SELF-02 keeps self fields and AgentOS-only optional statistics."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from contracts.knowledge_collections import KnowledgeCollectionsUsageResult
from nexent.storage.errors import Conflict, ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_search import knowledge_search_revision
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def self_capacity(mocker):
    from management.services.knowledge_base import personal_capacity as module

    row = {'knowledge_id': 1, 'index_name': 'kb-one', 'tenant_id': 'tenant-a', 'created_by': 'actor',
        'ingroup_permission': 'PRIVATE', 'group_ids': [], 'embedding_model_id': None, 'knowledge_sources': 'datamate'}
    actor = ServicePrincipal('actor', 'tenant-a')
    inputs = {'knowledge_bases': [row], 'personal_bytes': 5, 'quota_bytes': 10, 'quota_source': 'individual'}
    reader = SimpleNamespace(read_self=Mock(return_value=inputs), authorize_self=Mock())
    client = SimpleNamespace(knowledge_collection_usage=AsyncMock(return_value=KnowledgeCollectionsUsageResult(items=[
        {'knowledge_id': 1, 'expected_revision': knowledge_search_revision(row), 'present': True,
            'statistics': {'record_count': 2, 'size_bytes': 1024, 'source_count': 1}}])))

    async def blocking(name, action, *args, **kwargs):
        assert kwargs.pop('lane') == 'control-io' and kwargs.pop('owner') == 'management.knowledge_base'
        return action(*args, **kwargs)

    mocker.patch.object(module, 'run_blocking', side_effect=blocking)
    service = module.PersonalSelfCapacity(reader=reader, client=client)
    return SimpleNamespace(**locals())


async def test_self_fields_datamate_and_actual_actor(self_capacity):
    s = self_capacity
    result = await s.service.read(s.actor, context=context())
    assert result == {'used_bytes': 5, 'used_readable': '5 B', 'es_physical_bytes': 1024, 'es_physical_readable': '1.0 KB',
        'quota_bytes': 10, 'quota_readable': '10 B', 'quota_source': 'individual', 'usage_rate': 50.0, 'is_over_quota': False, 'kb_count': 1}
    request, user, tenant = s.client.knowledge_collection_usage.call_args.args
    assert (request.view, request.knowledge_ids, user, tenant) == ('usage', [1], 'actor', 'tenant-a')
    assert request.expected_revisions == {1: knowledge_search_revision(s.row)}
    assert s.reader.read_self.call_args.args == (s.actor,) and s.reader.authorize_self.call_count == 1


@pytest.mark.parametrize(('limit', 'used', 'rate', 'over'), [(0, 5, 100.0, True), (-1, 5, 100.0, True),
    (0, 0, 0.0, False), (None, 5, None, False)])
async def test_original_zero_negative_and_unlimited_quota(self_capacity, limit, used, rate, over):
    s = self_capacity
    s.inputs.update(quota_bytes=limit, personal_bytes=used)
    result = await s.service.read(s.actor, context=context())
    assert result['usage_rate'] == rate and result['is_over_quota'] is over


@pytest.mark.parametrize('error', [RuntimeServiceTimeoutError('timeout'), RuntimeError('offline')])
async def test_original_optional_es_error_does_not_change_source_usage(self_capacity, error):
    s = self_capacity
    s.client.knowledge_collection_usage.side_effect = error
    result = await s.service.read(s.actor, context=context())
    assert result['used_bytes'] == 5 and result['es_physical_bytes'] == 0
    assert s.client.knowledge_collection_usage.await_count == 1


@pytest.mark.parametrize(('status', 'kind'), [(403, ScopeDenied), (409, Conflict)])
async def test_grant_refusal_is_not_zero(self_capacity, status, kind):
    s = self_capacity
    s.client.knowledge_collection_usage.side_effect = RuntimeUpstreamError(status, b'refused', {})
    with pytest.raises(kind):
        await s.service.read(s.actor, context=context())
    assert s.client.knowledge_collection_usage.await_count == 1


async def test_empty_user_preserves_zero_es_and_skips_runtime(self_capacity):
    s = self_capacity
    s.inputs.update(knowledge_bases=[], personal_bytes=0)
    result = await s.service.read(s.actor, context=context())
    assert result['used_bytes'] == result['kb_count'] == result['es_physical_bytes'] == 0
    s.client.knowledge_collection_usage.assert_not_awaited()


async def test_current_identity_revoked_after_statistics(self_capacity):
    s = self_capacity
    s.reader.authorize_self.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        await s.service.read(s.actor, context=context())


async def test_same_collection_aliases_request_once_and_keep_legacy_count(self_capacity):
    s = self_capacity
    second = {**s.row, 'knowledge_id': 2}
    s.inputs['knowledge_bases'].append(second)
    s.client.knowledge_collection_usage.return_value = KnowledgeCollectionsUsageResult(items=[{
        'knowledge_id': 2, 'expected_revision': knowledge_search_revision(second), 'present': True,
        'statistics': {'record_count': 2, 'source_count': 1, 'size_bytes': 1024}}])
    result = await s.service.read(s.actor, context=context())
    assert result['es_physical_bytes'] == 2048 and result['kb_count'] == 2
    assert s.client.knowledge_collection_usage.call_args.args[0].knowledge_ids == [2]


async def test_root_deadline_sets_cancelled_and_logs_once(self_capacity, mocker, caplog):
    import asyncio

    from management.services.knowledge_base import personal_capacity as module
    from nexent.storage.errors import DeadlineExceeded
    from nexent.storage.models import OperationContext

    saved, exited = [], []

    async def expired(self, actor, *, context):
        saved.append(context)
        try:
            await asyncio.Event().wait()
        finally:
            exited.append(True)

    mocker.patch.object(module.PersonalSelfCapacity, 'read', new=expired)
    mocker.patch.object(module, 'OperationContext', side_effect=lambda name, deadline, **kwargs:
        OperationContext(name, module.monotonic() + .02, **kwargs))
    with pytest.raises(DeadlineExceeded):
        await module.personal_self_capacity(self_capacity.actor)
    assert saved[0].cancelled.is_set() and exited == [True]
    assert len([r for r in caplog.records if r.levelname == 'WARNING' and 'personal_capacity_timeout' in r.message]) == 1
