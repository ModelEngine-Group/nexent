# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DELETE-COORD-01/02: persistent phases surround controlled AgentOS calls."""

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from contracts.agentos_knowledge import KnowledgeJobState
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from management.services.knowledge_base.deletion_coordinator import DeletionCoordinator
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_deletion_contract import intent
from test.backend.services.test_knowledge_deletion_journal import (
    setup as journal_setup,  # noqa: F401
)
from test.backend.services.test_knowledge_ingestion_coordinator import (
    sqlite_threads,  # noqa: F401
)
from test.backend.services.test_knowledge_source_deletion import (
    setup as source_setup,  # noqa: F401
)


@pytest.fixture
async def setup(sqlite_threads, journal_setup, resources):  # noqa: F811
    s = journal_setup
    _, update, engine, tables = resources
    actor = SimpleNamespace(user_id='user-a', tenant_id='tenant-a')
    manager = ThreadManager(service_name='deletion-ut', lane_policies={
        'control-io': LanePolicy(name='control-io', max_workers=1, max_queue_size=8,
                                queue_timeout_seconds=1, cancel_grace_seconds=1, shutdown_grace_seconds=2),
    })
    manager.start()
    set_default_thread_manager(manager)
    counters = {'open': 0, 'close': 0}

    @contextmanager
    def ports(selected, *, context):
        context.remaining()
        counters['open'] += 1
        records = s.port(user=selected.user_id, tenant=selected.tenant_id)
        authorized = bind_cleanse_resources(StorageScope('management', selected.tenant_id, selected.user_id, set(tables)), engine)
        try:
            yield records, authorized
        finally:
            authorized.close()
            records.close()
            counters['close'] += 1

    cleanse = Mock()
    cleanse.cancel_file.return_value = {'execution_drained': True, 'task_ids': [], 'cancelled_count': 0}
    client = SimpleNamespace(delete_knowledge_file=AsyncMock(), inspect_knowledge_file=AsyncMock())
    source = Mock()
    coordinator = DeletionCoordinator(cleanse, client, ports=ports, source=source)

    def row():
        with s.engine.connect() as connection:
            return dict(connection.execute(sa.select(s.table)).mappings().one())

    def child(status='cleanup_pending', **kwargs):
        return KnowledgeJobState(**s.intent.runtime_lookup(actor.tenant_id).model_dump(), status=status, **kwargs)

    try:
        yield SimpleNamespace(**locals())
    finally:
        clear_default_thread_manager(manager)
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids
        assert counters['open'] == counters['close']


async def test_submit_once_then_inspect_until_runtime_and_cleanse_are_physically_done(setup):
    s = setup
    await s.coordinator.admit(s.s.intent, s.actor, context=context())
    s.client.delete_knowledge_file.return_value = s.child()
    state = await s.coordinator.advance(s.s.intent.file_id, s.actor, context=context())
    assert state['stage'] == 'DELETE_RUNTIME_PENDING'
    s.client.delete_knowledge_file.assert_awaited_once_with(s.s.intent.runtime_request(), user_id='user-a', tenant_id='tenant-a')
    s.cleanse.cancel_file.assert_not_called()
    s.source.assert_not_called()
    s.client.inspect_knowledge_file.return_value = s.child('deleted', physical_cleanup_complete=True)
    s.cleanse.cancel_file.return_value['execution_drained'] = False
    state = await s.coordinator.advance(s.s.intent.file_id, s.actor, context=context())
    assert state['stage'] == 'DELETE_CLEANSE_PENDING'
    s.source.assert_not_called()
    s.cleanse.cancel_file.return_value['execution_drained'] = True
    s.source.return_value = {'stage': 'DELETE_DONE', 'status': 'DELETED'}
    result = await s.coordinator.advance(s.s.intent.file_id, s.actor, context=context())
    assert result == s.source.return_value
    assert s.source.call_args.args[0]['stage'] == 'DELETE_SOURCE_PENDING'
    assert s.client.delete_knowledge_file.await_count == 1
    assert s.client.inspect_knowledge_file.await_count == 1


async def test_unknown_submission_404_and_timeout_never_resubmit(setup):
    s = setup
    await s.coordinator.admit(s.s.intent, s.actor, context=context())
    s.client.delete_knowledge_file.side_effect = RuntimeServiceTimeoutError('uncertain')
    with pytest.raises(RuntimeServiceTimeoutError):
        await s.coordinator.advance(s.s.intent.file_id, s.actor, context=context())
    assert s.row()['stage'] == 'DELETE_RUNTIME_SUBMITTING'
    s.client.inspect_knowledge_file.side_effect = RuntimeUpstreamError(404, b'missing', {})
    assert (await s.coordinator.advance(s.s.intent.file_id, s.actor, context=context()))['stage'] == 'DELETE_RUNTIME_SUBMITTING'
    s.client.inspect_knowledge_file.side_effect = RuntimeUpstreamError(403, b'denied', {})
    with pytest.raises(RuntimeUpstreamError):
        await s.coordinator.advance(s.s.intent.file_id, s.actor, context=context())
    assert s.client.delete_knowledge_file.await_count == 1
    s.source.assert_not_called()


async def test_source_only_does_not_access_runtime_or_cancel_cleanse(setup):
    s = setup
    value = intent(scope='source_only')
    await s.coordinator.admit(value, s.actor, context=context())
    s.source.return_value = {'status': 'COMPLETED', 'stage': 'SOURCE_DELETED'}
    assert await s.coordinator.advance(value.file_id, s.actor, context=context()) == s.source.return_value
    s.client.delete_knowledge_file.assert_not_called()
    s.client.inspect_knowledge_file.assert_not_called()
    s.cleanse.cancel_file.assert_not_called()


async def test_current_permissions_and_original_request_identity_are_checked_each_time(setup):
    s = setup
    await s.coordinator.admit(s.s.intent, s.actor, context=context())
    s.update('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        await s.coordinator.advance(s.s.intent.file_id, s.actor, context=context())
    s.client.delete_knowledge_file.assert_not_called()
    s.update('cleanse_memberships', delete_flag='N')
    with pytest.raises(ScopeDenied):
        await s.coordinator.advance(s.s.intent.file_id, SimpleNamespace(user_id='editor-b', tenant_id='tenant-a'), context=context())
    s.source.assert_not_called()


async def test_wrong_runtime_identity_cannot_open_source_gate(setup):
    s = setup
    await s.coordinator.admit(s.s.intent, s.actor, context=context())
    s.client.delete_knowledge_file.return_value = s.child('deleted', physical_cleanup_complete=True).model_copy(update={'job_id': 'f' * 32})
    with pytest.raises(ScopeDenied):
        await s.coordinator.advance(s.s.intent.file_id, s.actor, context=context())
    s.source.assert_not_called()


async def test_whole_operation_deadline_cancels_http_and_blocks_late_writes(setup):
    s = setup
    await s.coordinator.admit(s.s.intent, s.actor, context=context())
    stopped = asyncio.Event()

    async def hang(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    s.client.delete_knowledge_file.side_effect = hang
    started = monotonic()
    with pytest.raises(DeadlineExceeded):
        await s.coordinator.advance(s.s.intent.file_id, s.actor,
                                    context=replace(context(), deadline=monotonic() + .1))
    assert monotonic() - started < 1 and stopped.is_set()
    assert s.row()['stage'] == 'DELETE_RUNTIME_SUBMITTING'
    s.source.assert_not_called()


async def test_stale_phase_cannot_issue_another_runtime_write(setup):
    s = setup
    admitted = await s.coordinator.admit(s.s.intent, s.actor, context=context())
    await s.coordinator._blocking('reserve', s.coordinator._change, admitted, s.actor, context(), 'begin_runtime')
    with pytest.raises(Conflict):
        await s.coordinator._blocking('stale', s.coordinator._change, admitted, s.actor, context(), 'begin_runtime')
    s.client.delete_knowledge_file.assert_not_called()


async def test_default_source_path_finishes_real_journal_and_ledger_after_both_drains(setup, source_setup, monkeypatch):  # noqa: F811
    from contracts.knowledge import (
        STORAGE_LEDGER_DATASET,
        STORAGE_LEDGER_HISTORY_DATASET,
    )
    from contracts.knowledge_deletion import DELETION_DATASET
    from nexent.storage.models import DeleteReceipt

    from infrastructure import knowledge_deletion
    from infrastructure.rdb.knowledge_deletion import bind_deletion_records

    s, storage = setup, source_setup
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(status='COMPLETED', stage='COMPLETE', deletion_request=None))

    @contextmanager
    def ports(actor, *, context):
        with s.ports(actor, context=context) as (_, authorized):
            records = bind_deletion_records(StorageScope('management', actor.tenant_id, actor.user_id,
                                            {DELETION_DATASET, STORAGE_LEDGER_DATASET, STORAGE_LEDGER_HISTORY_DATASET}), s.s.engine)
            try:
                yield records, authorized
            finally:
                records.close()

    @contextmanager
    def objects(row, actor, *, context):
        assert (row['file_id'], actor.user_id) == (storage.value.file_id, 'user-a')
        yield storage.objects

    def delete(target, *, context):
        assert s.row()['stage'] == 'DELETE_SOURCE_DELETING'
        assert storage.records.get(STORAGE_LEDGER_HISTORY_DATASET, 17, context=context)['status'] == 'COMMITTED'
        return DeleteReceipt(context.operation_id, True)

    monkeypatch.setattr(knowledge_deletion, 'deletion_source_objects', objects)
    storage.objects.delete.side_effect = delete
    s.coordinator.ports = ports
    s.coordinator.source = s.coordinator._delete_source
    await s.coordinator.admit(storage.value, s.actor, context=context())
    s.client.delete_knowledge_file.return_value = s.child('deleted', physical_cleanup_complete=True)
    done = await s.coordinator.advance(storage.value.file_id, s.actor, context=context())
    assert done['stage'] == 'DELETE_DONE' and done['status'] == 'DELETED'
    assert (await s.coordinator.advance(storage.value.file_id, s.actor, context=context()))['version'] == done['version']
    assert storage.objects.delete.call_count == 1 and s.cleanse.cancel_file.call_count == 1
    assert s.client.delete_knowledge_file.await_count == 1


async def test_parent_deadline_closes_signed_agentos_http_client_and_next_call_only_inspects(setup, monkeypatch):
    import httpx
    from contracts.agentos_knowledge import KnowledgeOperation
    from contracts.constants import environment

    from infrastructure.agentos_client import AgentOSClient
    from infrastructure.agentos_identity import ServicePrincipal, verify_call

    s = setup
    monkeypatch.setattr(environment, 'JWT_SECRET', 'synthetic-delete-coordinator-key')
    clients, messages, cancelled = [], [], []

    async def respond(message):
        operation = KnowledgeOperation.DELETE if not messages else KnowledgeOperation.INSPECT
        assert message.url.path == '/api' + operation.value
        token = message.headers['Authorization'].removeprefix('Bearer ')
        assert verify_call(token, operation, message.content) == ServicePrincipal('user-a', 'tenant-a')
        messages.append(message)
        if operation is KnowledgeOperation.INSPECT:
            return httpx.Response(404, json={'detail': 'not observed'})
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    def create(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    s.coordinator.client = AgentOSClient('http://runtime', create)
    await s.coordinator.admit(s.s.intent, s.actor, context=context())
    with pytest.raises(DeadlineExceeded):
        await s.coordinator.advance(s.s.intent.file_id, s.actor,
                                    context=replace(context(), deadline=monotonic() + .1))
    assert len(messages) == len(clients) == 1 and clients[0].is_closed and cancelled == [True]
    pending = await s.coordinator.advance(s.s.intent.file_id, s.actor, context=context())
    assert pending['stage'] == 'DELETE_RUNTIME_SUBMITTING'
    assert len(messages) == len(clients) == 2 and all(client.is_closed for client in clients)
    s.source.assert_not_called()


async def test_waiting_publication_does_not_call_runtime_until_confirmed_then_uses_same_delete_identity(setup):
    from test.backend.services.test_knowledge_deletion_pending_publication import (
        publishing,
    )

    s = setup
    value = publishing(s.s)
    await s.coordinator.admit(value, s.actor, context=context())
    waiting = await s.coordinator.advance(value.file_id, s.actor, context=context())
    assert waiting['status'] == 'UPLOADING' and waiting['stage'] == 'SOURCE_UPLOAD'
    s.client.delete_knowledge_file.assert_not_called()
    s.source.assert_not_called()
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(status='UPLOADED', stage='UPLOAD', source_space='files',
                                                     source_key='source.txt', source_revision='etag:one', source_sha256='a' * 64,
                                                     storage_object_id=17, version=waiting['version'] + 1))
    s.client.delete_knowledge_file.return_value = s.child()
    row = await s.coordinator.advance(value.file_id, s.actor, context=context())
    assert row['stage'] == 'DELETE_RUNTIME_PENDING'
    s.client.delete_knowledge_file.assert_awaited_once_with(value.runtime_request(), user_id='user-a', tenant_id='tenant-a')
    assert row['deletion_request']['source']['version'] == 'etag:one'
