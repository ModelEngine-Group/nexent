# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deprovision preparation preserves the issuer and never counts pending as success."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from management.services.knowledge_base import deprovision as service
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Page


@pytest.fixture
def cleanup(monkeypatch):
    records = SimpleNamespace(query=Mock(return_value=Page(({'index_name': 'private-kb'},))))

    @contextmanager
    def ports(actor, *, context, readonly):
        assert actor.user_id == 'admin' and actor.tenant_id == 'target-tenant'
        assert readonly
        yield records, object()

    async def blocking(name, fn, *args, **kwargs):
        assert kwargs.pop('lane') == 'control-io'
        assert kwargs.pop('owner') == 'management.knowledge_base'
        return fn(*args, **kwargs)

    coordinator = SimpleNamespace(admit_owner_cleanup=AsyncMock(), request_owner_cleanup=AsyncMock())
    monkeypatch.setattr(service, 'knowledge_admission_ports', ports)
    monkeypatch.setattr(service, 'run_blocking', blocking)
    monkeypatch.setattr(service, '_coordinator', Mock(return_value=coordinator))
    return SimpleNamespace(records=records, coordinator=coordinator)


async def test_prepare_admits_as_actual_admin_without_runtime_execution(cleanup):
    plan = await service.prepare_private_cleanup('owner', 'target-tenant', 'admin')
    call = cleanup.coordinator.admit_owner_cleanup.call_args
    assert call.args[:2] == ('private-kb', 'owner')
    assert call.args[2].user_id == 'admin'
    assert call.kwargs['purpose'] == 'user_deletion'
    cleanup.coordinator.request_owner_cleanup.assert_not_awaited()
    assert plan.indexes == ('private-kb',) and plan.failed == 0
    query = cleanup.records.query.call_args.args[1]
    assert {(term.field, term.value) for term in query.where.terms} == {
        ('created_by', 'owner'), ('ingroup_permission', 'PRIVATE'), ('knowledge_sources', 'elasticsearch')}


async def test_preparation_pages_without_truncating_scope(cleanup):
    cleanup.records.query.side_effect = [Page(({'index_name': 'a'},), 'next'), Page(({'index_name': 'b'},))]
    plan = await service.prepare_private_cleanup('owner', 'target-tenant', 'admin', purpose='tenant_deletion')
    assert plan.indexes == ('a', 'b')
    assert cleanup.records.query.call_args_list[1].args[2].cursor == 'next'
    assert all(call.kwargs['purpose'] == 'tenant_deletion'
               for call in cleanup.coordinator.admit_owner_cleanup.call_args_list)


async def test_denied_or_malformed_preparation_is_failed_not_submitted(cleanup):
    cleanup.records.query.return_value = Page(({'index_name': 'a'}, {'index_name': None}))
    cleanup.coordinator.admit_owner_cleanup.side_effect = ScopeDenied()
    plan = await service.prepare_private_cleanup('owner', 'target-tenant', 'admin')
    assert plan.total == plan.failed == 2 and not plan.indexes
    assert await service.execute_cleanup(plan) == {'total': 2, 'succeeded': 0, 'failed': 2, 'pending': 0}
    cleanup.coordinator.request_owner_cleanup.assert_not_awaited()


@pytest.mark.parametrize('phase,deleted,expected', [('files', 'N', 'pending'), ('deleted', 'Y', 'succeeded')])
async def test_execute_requires_confirmed_terminal_and_keeps_actual_issuer(cleanup, phase, deleted, expected):
    plan = await service.prepare_private_cleanup('owner', 'target-tenant', 'admin')
    cleanup.coordinator.request_owner_cleanup.return_value = {
        'knowledge_id': 1, 'index_name': 'private-kb', 'delete_flag': deleted,
        'deletion_request': {'schema_version': 1, 'knowledge_id': 1, 'index_name': 'private-kb',
                             'user_id': 'admin', 'phase': phase,
                             'owner_cleanup': {'purpose': 'user_deletion', 'owner_user_id': 'owner',
                                               'actor_tenant_id': 'operator-tenant'}}}
    result = await service.execute_cleanup(plan)
    assert result[expected] == result['total'] == 1
    assert result['succeeded' if expected == 'pending' else 'pending'] == result['failed'] == 0
    call = cleanup.coordinator.request_owner_cleanup.call_args
    assert call.args[2].user_id == 'admin' and call.args[2].tenant_id == 'target-tenant'


async def test_execute_error_does_not_replay(cleanup):
    plan = await service.prepare_private_cleanup('owner', 'target-tenant', 'admin')
    cleanup.coordinator.request_owner_cleanup.side_effect = ScopeDenied()
    assert await service.execute_cleanup(plan) == {'total': 1, 'succeeded': 0, 'failed': 1, 'pending': 0}
    cleanup.coordinator.request_owner_cleanup.assert_awaited_once()


async def test_no_private_kb_preserves_absent_summary(cleanup):
    cleanup.records.query.return_value = Page(())
    plan = await service.prepare_private_cleanup('owner', 'target-tenant', 'admin')
    assert await service.execute_cleanup(plan) is None
    cleanup.coordinator.admit_owner_cleanup.assert_not_awaited()


async def test_selection_failure_is_reported_without_blocking_credential_revocation(cleanup, caplog):
    cleanup.records.query.side_effect = RuntimeError('selection failed')
    plan = await service.prepare_private_cleanup('owner', 'target-tenant', 'admin')
    assert plan.total is None and not plan.indexes
    assert await service.execute_cleanup(plan) is None
    cleanup.coordinator.admit_owner_cleanup.assert_not_awaited()
    assert 'private_knowledge_selection_failed' in caplog.text


async def test_coordinator_unavailable_counts_preparation_failures_without_replay(cleanup, monkeypatch):
    monkeypatch.setattr(service, '_coordinator', Mock(side_effect=RuntimeError('unavailable')))
    plan = await service.prepare_private_cleanup('owner', 'target-tenant', 'admin')
    assert not plan.indexes and plan.failed == plan.total == 1
    assert await service.execute_cleanup(plan) == {'total': 1, 'succeeded': 0, 'failed': 1, 'pending': 0}


@pytest.mark.parametrize('change', [{'user_id': 'owner'}, {'owner_cleanup': None}, {'index_name': 'foreign'}])
async def test_wrong_returned_authority_is_failed_not_pending(cleanup, change):
    plan = await service.prepare_private_cleanup('owner', 'target-tenant', 'admin')
    cleanup.coordinator.request_owner_cleanup.return_value = {
        'knowledge_id': 1, 'index_name': 'private-kb', 'delete_flag': 'N',
        'deletion_request': {'schema_version': 1, 'knowledge_id': 1, 'index_name': 'private-kb',
            'user_id': 'admin', 'phase': 'files',
            'owner_cleanup': {'purpose': 'user_deletion', 'owner_user_id': 'owner', 'actor_tenant_id': 'operator'}, **change}}
    assert await service.execute_cleanup(plan) == {'total': 1, 'succeeded': 0, 'failed': 1, 'pending': 0}


async def test_tenant_plan_selects_shared_local_only_and_never_requires_a_creator(cleanup):
    cleanup.coordinator.admit_tenant_cleanup = AsyncMock()
    plan = await service.prepare_tenant_cleanup('target-tenant', 'admin')
    cleanup.coordinator.admit_tenant_cleanup.assert_awaited_once()
    cleanup.coordinator.admit_owner_cleanup.assert_not_awaited()
    assert plan.owner_user_id is None and plan.purpose == 'tenant_deletion'
    query = cleanup.records.query.call_args.args[1]
    assert [(term.field, term.operator, term.value) for term in query.where.terms] == [
        ('ingroup_permission', 'in', ['EDIT', 'READ_ONLY']), ('knowledge_sources', 'eq', 'elasticsearch')]


async def test_tenant_plan_executes_standard_parent_and_keeps_pending_separate(cleanup):
    cleanup.coordinator.admit_tenant_cleanup = AsyncMock()
    cleanup.coordinator.request_tenant_cleanup = AsyncMock(return_value={
        'knowledge_id': 1, 'index_name': 'private-kb', 'delete_flag': 'N',
        'deletion_request': {'schema_version': 1, 'knowledge_id': 1, 'index_name': 'private-kb', 'user_id': 'admin',
                             'phase': 'files', 'tenant_cleanup': {'actor_tenant_id': 'operator'}}})
    plan = await service.prepare_tenant_cleanup('target-tenant', 'admin')
    assert await service.execute_cleanup(plan) == {'total': 1, 'succeeded': 0, 'failed': 0, 'pending': 1}
    cleanup.coordinator.request_tenant_cleanup.assert_awaited_once()
    cleanup.coordinator.request_owner_cleanup.assert_not_awaited()


@pytest.mark.parametrize('owner', [None, ''])
async def test_private_preparation_cannot_be_reinterpreted_as_tenant_scope(cleanup, owner):
    with pytest.raises(ScopeDenied):
        await service.prepare_private_cleanup(owner, 'target-tenant', 'admin')
    cleanup.records.query.assert_not_called()
