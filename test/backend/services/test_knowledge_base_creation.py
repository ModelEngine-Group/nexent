# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-KB-CREATE-01/02 keep catalog assembly outside Runtime execution."""

import asyncio
from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from contracts.agentos import ModelMetadata
from contracts.knowledge_collections import KnowledgeCollectionEnsured
from management.services.knowledge_base import creation as module
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import OperationContext, WriteOutcome

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def boundary(mocker):
    actor = ServicePrincipal('operator', 'tenant-a')
    events, contexts = [], []
    records = MagicMock()
    records.scope = SimpleNamespace(service_role='management', tenant_id=actor.tenant_id,
                                   actor_id=actor.user_id, system=False, resource_prefix=None)
    records.transaction.return_value.__enter__.return_value = records
    records.create.side_effect = lambda *args, **kwargs: events.append('create') or {
        'knowledge_id': 7, 'index_name': None, 'knowledge_name': 'KB', 'version': 1}
    records.patch.return_value = SimpleNamespace(outcome=WriteOutcome.CONFIRMED, matched=True)

    @contextmanager
    def ports(owner, *, context, writable=False, knowledge_name=None):
        assert owner == actor and writable and knowledge_name == 'KB'
        contexts.append(context)
        yield records
        events.append('committed')

    row = {'knowledge_id': 7, 'index_name': '7-fixed', 'tenant_id': actor.tenant_id,
           'knowledge_sources': 'elasticsearch', 'deletion_request': None, 'embedding_model_id': 2}
    reader = SimpleNamespace(knowledge=Mock(side_effect=lambda *a, **kw: events.append('read') or row))
    model = ModelMetadata(model_id=2, model_type='embedding', display_name='Display', model_name='embed',
                          qualified_name='repo/embed', revision='r1', embedding_dimensions=3)
    client = SimpleNamespace(get_model=AsyncMock(return_value=model))

    async def ensure(request, user, tenant):
        assert events == ['create', 'committed', 'read'] and (user, tenant) == (actor.user_id, actor.tenant_id)
        return KnowledgeCollectionEnsured(knowledge_id=request.knowledge_id, expected_revision=request.expected_revision,
                                          dimensions=request.dimensions, present=True, metric='cosine')

    client.ensure_knowledge_collection = AsyncMock(side_effect=ensure)

    async def blocking(name, action, *args, **kwargs):
        kwargs.pop('lane'); kwargs.pop('owner')
        contexts.append(kwargs['context'])
        return action(*args, **kwargs)

    mocker.patch.object(module, 'run_blocking', side_effect=blocking)
    mocker.patch.object(module, 'uuid4', return_value=SimpleNamespace(hex='fixed'))
    policy = mocker.patch.object(module, 'enforce_catalog_creation')
    return SimpleNamespace(**locals())


async def invoke(s, **kwargs):
    return await module.create_knowledge_base(' KB ', s.actor, embedding_model_id=2,
        ports=s.ports, client=s.client, reader=s.reader, **kwargs)


@pytest.mark.parametrize("native", [False, True])
async def test_creation_commits_directory_then_ensures_as_actual_actor(boundary, monkeypatch, native):
    monkeypatch.setattr(module.environment, "KNOWLEDGE_RUNTIME_HYBRID_ENABLED", native)
    s = boundary
    result = await invoke(s, user_role='ADMIN', ingroup_permission='READ_ONLY', group_ids=[1, 9],
                          preserve_source_file=False, quota_limit_bytes=12)
    assert result == {'status': 'success', 'message': 'Index 7-fixed created successfully', 'id': '7-fixed',
                      'knowledge_id': 7, 'name': 'KB', 'embedding_model_name': 'Display', 'model_type': 'embedding'}
    values = s.records.create.call_args.args[1]
    assert values == {'knowledge_name': 'KB', 'knowledge_describe': '', 'knowledge_sources': 'elasticsearch',
                      'embedding_model_id': 2, 'embedding_model_name': 'Display', 'ingroup_permission': 'READ_ONLY',
                      'group_ids': '1,9', 'preserve_source_file': False, 'quota_limit_bytes': 12}
    assert s.records.patch.call_args.args[2].set_values == {'index_name': '7-fixed'}
    assert s.records.patch.call_args.kwargs['expected'].value == '1'
    s.policy.assert_called_once()
    s.reader.knowledge.assert_called_once_with('7-fixed', s.actor, edit=True, context=s.contexts[0])
    s.client.get_model.assert_awaited_once_with(2, 'operator', 'tenant-a')
    request = s.client.ensure_knowledge_collection.await_args.args[0]
    assert request.dimensions == 3 and request.model_binding.model_id == 2 and request.model_binding.revision == 'r1'
    assert request.native_documents is native
    assert all(ctx is s.contexts[0] for ctx in s.contexts) and s.contexts[0].cancelled.is_set()
    s.records.delete.assert_not_called()


async def test_user_role_forces_private_and_raw_model_name_fallback(boundary):
    s = boundary
    s.model.display_name = None
    result = await invoke(s, user_role='USER', group_ids=[3], ingroup_permission='EDIT', embedding_dim=5)
    values = s.records.create.call_args.args[1]
    assert values['ingroup_permission'] == 'PRIVATE' and values['group_ids'] is None
    assert values['preserve_source_file'] is True and 'quota_limit_bytes' not in values
    assert result['embedding_model_name'] == 'embed'
    assert s.client.ensure_knowledge_collection.await_args.args[0].dimensions == 5


@pytest.mark.parametrize('field,value', [('model_id', 3), ('model_type', 'llm'), ('embedding_dimensions', None)])
async def test_invalid_model_metadata_never_creates_directory(boundary, field, value):
    s = boundary
    setattr(s.model, field, value)
    with pytest.raises(ValueError if field == 'model_type' else InvalidInput):
        await invoke(s)
    s.records.create.assert_not_called()
    s.client.ensure_knowledge_collection.assert_not_awaited()


@pytest.mark.parametrize('error', [OutcomeUnknown(), ScopeDenied(), asyncio.CancelledError()])
async def test_failed_or_cancelled_ensure_retains_directory_without_replay(boundary, error):
    s = boundary
    s.client.ensure_knowledge_collection.side_effect = error
    with pytest.raises(type(error)) as caught:
        await invoke(s)
    assert caught.value is error
    assert s.records.create.call_count == 1 and s.client.ensure_knowledge_collection.await_count == 1
    s.records.delete.assert_not_called()


async def test_failed_catalog_transaction_never_calls_runtime(boundary):
    s = boundary
    s.records.transaction.return_value.__exit__.side_effect = OutcomeUnknown()
    with pytest.raises(OutcomeUnknown):
        await invoke(s)
    s.client.ensure_knowledge_collection.assert_not_awaited()
    assert s.records.create.call_count == 1


async def test_wrong_scope_is_rejected_before_write(boundary):
    s = boundary
    s.records.scope.actor_id = 'creator'
    with pytest.raises(ScopeDenied):
        await invoke(s)
    s.records.create.assert_not_called()


async def test_total_deadline_does_not_replay_or_delete(boundary):
    s = boundary

    async def slow(*args):
        await asyncio.sleep(1)

    s.client.ensure_knowledge_collection.side_effect = slow
    with pytest.raises(DeadlineExceeded):
        await invoke(s, operation_seconds=0.03)
    assert s.records.create.call_count == 1 and s.client.ensure_knowledge_collection.await_count == 1
    s.records.delete.assert_not_called()


async def test_existing_parent_deadline_is_preserved(boundary):
    s = boundary
    context = OperationContext('parent', monotonic() + 0.03)

    async def slow(*args):
        await asyncio.sleep(1)

    s.client.get_model.side_effect = slow
    with pytest.raises(DeadlineExceeded):
        await invoke(s, context=context)
    assert context.cancelled is None
    s.records.create.assert_not_called()


async def test_mismatched_ensure_receipt_never_returns_success(boundary):
    s = boundary
    s.client.ensure_knowledge_collection.side_effect = None
    s.client.ensure_knowledge_collection.return_value = KnowledgeCollectionEnsured(
        knowledge_id=8, expected_revision='a' * 64, dimensions=3, metric='cosine', present=True)
    with pytest.raises(Conflict):
        await invoke(s)
    s.records.delete.assert_not_called()


@pytest.mark.parametrize('groups,expected', [(None, None), ([], ''), ([3], '3')])
async def test_original_partial_and_empty_group_settings(boundary, groups, expected):
    s = boundary
    await invoke(s, user_role='ADMIN', ingroup_permission='READ_ONLY', group_ids=groups)
    values = s.records.create.call_args.args[1]
    assert values['ingroup_permission'] == 'READ_ONLY'
    assert values.get('group_ids') == expected
    assert ('group_ids' in values) == (groups is not None)


async def test_multi_embedding_preserves_selected_id_and_type(boundary):
    s = boundary
    s.model.model_type = 'multi_embedding'
    result = await invoke(s)
    assert result['model_type'] == 'multi_embedding'
    assert s.records.create.call_args.args[1]['embedding_model_id'] == 2


@pytest.mark.parametrize('error', [ValueError('catalog failed'), OutcomeUnknown()])
async def test_catalog_write_error_stops_execution(boundary, error):
    s = boundary
    s.records.create.side_effect = error
    with pytest.raises(type(error)) as caught:
        await invoke(s)
    assert caught.value is error and s.records.create.call_count == 1
    s.records.patch.assert_not_called()
    s.client.ensure_knowledge_collection.assert_not_awaited()


@pytest.mark.parametrize('field,value', [('knowledge_name', ' '), ('embedding_model_id', None),
                                      ('embedding_model_id', True), ('embedding_dim', -1)])
async def test_invalid_request_prevents_model_and_catalog_io(boundary, field, value):
    s = boundary
    args = {'knowledge_name': 'KB', 'actor': s.actor, 'embedding_model_id': 2, 'client': s.client, 'ports': s.ports}
    args[field] = value
    with pytest.raises((ValueError, InvalidInput)):
        await module.create_knowledge_base(**args)
    s.client.get_model.assert_not_awaited()
    s.records.create.assert_not_called()


async def test_duplicate_or_quota_policy_error_is_not_wrapped(boundary):
    from contracts.errors.exceptions import AppException, DuplicateError

    s = boundary
    for error in (DuplicateError('duplicate'), AppException('060101', 'limit')):
        s.policy.side_effect = error
        with pytest.raises(type(error)) as caught:
            await invoke(s)
        assert caught.value is error
    s.records.create.assert_not_called()
    s.client.ensure_knowledge_collection.assert_not_awaited()
