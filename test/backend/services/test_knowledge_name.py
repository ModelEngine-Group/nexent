# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-KB-NAME-01/02 preserve tenant-local names through read-only SI."""

import asyncio
from contextlib import contextmanager
from threading import Event
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from management.services.knowledge_base import names as module
from nexent.storage.errors import (
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_catalog import bind_knowledge_catalog, knowledge


@pytest.fixture
def catalog():
    engine = sa.create_engine('sqlite://', execution_options={'schema_translate_map': {'nexent': None}})
    knowledge.create(engine)
    actor = ServicePrincipal('operator', 'tenant-a')
    rows = [
        (1, 'private', 'tenant-a', 'other', 'N', 'elasticsearch'),
        (2, 'external', 'tenant-a', 'operator', 'N', 'datamate'),
        (3, 'foreign', 'tenant-b', 'operator', 'N', 'elasticsearch'),
        (4, 'deleted', 'tenant-a', 'operator', 'Y', 'elasticsearch'),
        (5, 'duplicate', 'tenant-a', 'operator', 'N', 'elasticsearch'),
        (6, 'duplicate', 'tenant-a', 'other', 'N', 'elasticsearch'),
    ]
    with engine.begin() as connection:
        for key, name, tenant, creator, deleted, source in rows:
            connection.execute(knowledge.insert(), {'knowledge_id': key, 'knowledge_name': name, 'tenant_id': tenant,
                'index_name': 'kb-' + str(key), 'created_by': creator, 'delete_flag': deleted, 'knowledge_sources': source,
                'ingroup_permission': 'PRIVATE', 'version': 1})
    opened = []

    @contextmanager
    def ports(principal, *, context):
        assert principal == actor
        records = bind_knowledge_catalog(principal, engine)
        opened.append(records)
        try:
            yield records
        finally:
            records.close()

    yield SimpleNamespace(**locals())
    engine.dispose()


def context():
    return OperationContext('kb-name', monotonic() + 10)


@pytest.mark.parametrize('name,status', [
    ('private', 'exists_in_tenant'), ('external', 'exists_in_tenant'), ('duplicate', 'exists_in_tenant'),
    ('foreign', 'available'), ('deleted', 'available'), ('absent', 'available'),
    ('Private', 'available'), (' private ', 'available'),
])
def test_name_uses_exact_tenant_active_directory_without_physical_index_or_reader_dac(catalog, name, status):
    s = catalog
    assert module.name_status(name, s.actor, context=context(), ports=s.ports) == {'status': status}
    assert len(s.opened) == 1


@pytest.mark.parametrize('field,value', [
    ('tenant_id', 'tenant-b'), ('actor_id', 'other'), ('service_role', 'runtime'),
    ('system', True), ('resource_prefix', 'prefix'),
])
def test_corrupted_scope_never_queries_or_returns_available(field, value):
    actor = ServicePrincipal('operator', 'tenant-a')
    scope = SimpleNamespace(tenant_id=actor.tenant_id, actor_id=actor.user_id,
                            service_role='management', system=False, resource_prefix='')
    setattr(scope, field, value)
    records = SimpleNamespace(scope=scope, query=Mock())

    @contextmanager
    def ports(*args, **kwargs):
        yield records

    with pytest.raises(ScopeDenied):
        module.name_status('name', actor, context=context(), ports=ports)
    records.query.assert_not_called()


@pytest.mark.parametrize('error', [Unavailable(), OperationCancelled(), DeadlineExceeded()])
def test_read_failure_propagates_and_closes_instead_of_claiming_available(error):
    actor = ServicePrincipal('operator', 'tenant-a')
    records = SimpleNamespace(scope=SimpleNamespace(tenant_id=actor.tenant_id, actor_id=actor.user_id,
        service_role='management', system=False, resource_prefix=''), query=Mock(side_effect=error))
    closed = []

    @contextmanager
    def ports(*args, **kwargs):
        try:
            yield records
        finally:
            closed.append(True)

    with pytest.raises(type(error)) as caught:
        module.name_status('name', actor, context=context(), ports=ports)
    assert caught.value is error and closed == [True]
    call = records.query.call_args
    assert call.args[1].fields == ('knowledge_id',)
    assert call.args[2].limit == 1 and records.query.call_count == 1


@pytest.mark.parametrize('cancelled', [False, True])
def test_expired_or_cancelled_parent_never_opens_storage(cancelled):
    signal = Event()
    if cancelled:
        signal.set()
    parent = OperationContext('expired', monotonic() - 1, cancelled=signal)
    ports = Mock()
    with pytest.raises(OperationCancelled if cancelled else DeadlineExceeded):
        module.name_status('name', ServicePrincipal('operator', 'tenant-a'), context=parent, ports=ports)
    ports.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['success', 'error', 'timeout', 'cancel'])
async def test_async_owner_uses_one_bounded_managed_task_and_releases_signal(mocker, outcome, caplog):
    contexts = []
    actor = ServicePrincipal('operator', 'tenant-a')
    sentinel = Unavailable()

    async def blocking(phase, action, name, principal, **kwargs):
        assert phase == 'knowledge-name-check' and action is module.name_status
        assert (name, principal) == ('name', actor)
        assert kwargs['lane'] == 'control-io' and kwargs['owner'] == 'management.knowledge_base'
        contexts.append(kwargs['context'])
        if outcome == 'error':
            raise sentinel
        if outcome == 'cancel':
            raise asyncio.CancelledError()
        if outcome == 'timeout':
            await asyncio.Event().wait()
        return {'status': 'available'}

    worker = mocker.patch.object(module, 'run_blocking', side_effect=blocking)
    mocker.patch.object(module, 'NAME_CHECK_SECONDS', 0.02)
    with caplog.at_level('WARNING', logger=module.logger.name):
        if outcome == 'success':
            assert await module.check_knowledge_name('name', actor) == {'status': 'available'}
        else:
            expected = {'error': Unavailable, 'cancel': asyncio.CancelledError, 'timeout': TimeoutError}[outcome]
            with pytest.raises(expected):
                await module.check_knowledge_name('name', actor)
    assert worker.await_count == 1 and len(contexts) == 1 and contexts[0].cancelled.is_set()
    assert ('knowledge_name_check_timeout' in caplog.text) == (outcome == 'timeout')
    assert all(record.levelname != 'ERROR' for record in caplog.records)


def test_hybrid_aliases_keep_request_order_and_only_match_the_current_tenant(catalog):
    s = catalog
    requested = ['private', 'foreign', 'deleted', 'external', 'kb-1', 'Private', 'duplicate', 'private']
    assert module.search_indices(requested, s.actor, context=context(), ports=s.ports) == [
        'kb-1', 'foreign', 'deleted', 'kb-2', 'kb-1', 'Private', 'kb-5', 'kb-1',
    ]
    assert len(s.opened) == 1


def test_hybrid_aliases_paginate_the_catalog_without_changing_request_order(catalog):
    s = catalog
    with s.engine.begin() as conn:
        conn.execute(knowledge.insert(), [
            {'knowledge_id': key, 'knowledge_name': 'duplicate', 'tenant_id': s.actor.tenant_id,
             'index_name': f'repeated-{key}', 'created_by': s.actor.user_id, 'delete_flag': 'N', 'version': 1}
            for key in range(10, 1010)
        ])
    assert module.search_indices(['duplicate', 'kb-1'], s.actor, context=context(), ports=s.ports) == [
        'kb-5', 'kb-1',
    ]


@pytest.mark.asyncio
async def test_hybrid_resolution_propagates_storage_timeout_without_searching(mocker):
    worker = mocker.patch.object(module, 'run_blocking', side_effect=DeadlineExceeded())
    with pytest.raises(DeadlineExceeded):
        await module.resolve_search_index_names(['display', 'raw'], ServicePrincipal('operator', 'tenant-a'))
    assert worker.await_count == 1 and worker.await_args.kwargs['context'].cancelled.is_set()
