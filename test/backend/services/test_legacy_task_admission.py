# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Archived terminal tasks can be replaced only after current SI evidence matches."""

import base64
import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.knowledge_maintenance import LEGACY_TASKS
from management.services.knowledge_base.legacy_migration import LegacyMigrationService
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import FieldPatch, StorageScope

from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_legacy_ingestion_migration import (
    migration as migration,  # noqa: PLC0414
)
from test.backend.services.test_legacy_ingestion_migration import (
    records as records,  # noqa: PLC0414
)
from test.backend.services.test_legacy_ingestion_migration import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_legacy_ingestion_migration import (
    setup as setup,  # noqa: PLC0414
)
from test.backend.services.test_legacy_ingestion_migration import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)


@pytest.fixture
async def archived(migration, tmp_path):
    m = migration
    s = m.s
    await run_blocking('fixture', s.port.patch, 'knowledge_ingestion_files', s.value.file_id,
        FieldPatch(set_values={'process_task_id': 'old-task'}), context=context(), lane='control-io')
    original = m.source.page.side_effect
    m.source.page.side_effect = lambda *args, **kwargs: original(*args, **kwargs).model_copy(update={
        'files': [original(*args, **kwargs).files[0].model_copy(update={'issues': ['LEGACY_TASK_UNVERIFIED']})]})
    _, resource = await run_blocking('fixture', m.service._selected, 1, s.value.file_id, s.actor, context(), lane='control-io')
    raw = json.dumps({'status': 'SUCCESS', 'result': {'index_name': 'kb-one', 'file_id': s.value.file_id}}).encode()
    digest = hashlib.sha256(raw).hexdigest()
    value = {'binding': 'backend', 'key': 'celery-task-meta-old-task', 'encoding': 'raw', 'ttl_ms': -1,
        'value_base64': base64.b64encode(raw).decode(), 'sha256': digest}
    finding = {'task_id_hash': hashlib.sha256(b'old-task').hexdigest(), 'origin': 'pg_reference', 'status': 'SUCCESS',
        'revision': digest, 'file_id': s.value.file_id, 'auxiliary_present': [], 'issues': [], 'archive': [value]}
    frames = [{'kind': 'legacy_task_archive_inventory_start', 'operation_id': 'archive-1', 'knowledge_id': 1,
        'tenant_id': s.actor.tenant_id, 'actor_id': s.actor.user_id, 'legacy_quiesced': True, 'migration_ready': False},
        {'kind': 'legacy_task_archive_page', 'knowledge_id': 1, 'index_name': 'kb-one', 'tenant_id': s.actor.tenant_id,
            'actor_id': s.actor.user_id, 'knowledge_revision': resource.revision, 'tasks': [finding], 'snapshot': False},
        {'kind': 'legacy_task_archive_inventory_finished', 'operation_id': 'archive-1', 'scan_complete': True,
            'tasks': 1, 'knowledge_revision': resource.revision, 'snapshot': False, 'migration_ready': False}]
    path = tmp_path/'archive.jsonl'
    def write(): path.write_text(''.join(json.dumps(frame)+'\n' for frame in frames), encoding='utf-8')
    write()
    live = {**finding, 'task_id': 'old-task', 'index_matches': True, 'tenant_matches': None,
        'metadata_valid': True, 'result_present': True}
    port = Mock(scope=StorageScope('management', s.actor.tenant_id, s.actor.user_id, {LEGACY_TASKS}))
    port.get.return_value = live
    opened = []
    @contextmanager
    def tasks(actor, knowledge_id, index_name, *, known_tasks, **kwargs):
        assert actor == s.actor and knowledge_id == 1 and index_name == 'kb-one' and known_tasks == {'old-task'}
        opened.append(True)
        yield port
    service = LegacyMigrationService(ports=s.ports, client=s.client, sources=m.source,
        parser_version=s.value.parser_version, tasks=tasks)
    return SimpleNamespace(m=m, s=s, service=service, frames=frames, path=path, write=write, port=port,
        live=live, opened=opened)


async def test_archived_terminal_reference_is_saved_replaced_and_restored(archived):
    a = archived
    plan = await a.service.plan(1, a.s.value.file_id, a.s.actor, legacy_quiesced=True, task_archive=a.path, context=context())
    assert plan.legacy_snapshot.task_references == {'process_task_id': 'old-task'}
    assert plan.legacy_snapshot.task_archive_sha256 == hashlib.sha256(a.path.read_bytes()).hexdigest()
    row = await a.service.admit(plan, a.s.actor, task_archive=a.path, context=context())
    assert row['process_task_id'] != 'old-task' and row['stage'] == 'INGEST_ACCEPTED'
    assert row['ingestion_request']['legacy_snapshot']['task_references']['process_task_id'] == 'old-task'
    calls = a.port.get.call_count
    a.path.unlink()
    assert await a.service.admit(plan, a.s.actor, context=context()) == row
    assert a.port.get.call_count == calls
    restored = await a.service.restore(plan, a.s.actor, context=context())
    assert restored['process_task_id'] == 'old-task' and restored['ingestion_request'] is None
    assert await a.service.restore(plan, a.s.actor, context=context()) == restored


@pytest.mark.parametrize('change', ['unfinished', 'wrong-actor', 'wrong-file', 'running'])
async def test_invalid_archive_cannot_authorize_rebuild(archived, change):
    a = archived
    if change == 'unfinished': a.frames.pop()
    elif change == 'wrong-actor': a.frames[0]['actor_id'] = 'owner'
    elif change == 'wrong-file': a.frames[1]['tasks'][0]['file_id'] = 'c'*32
    else: a.frames[1]['tasks'][0]['status'] = 'STARTED'
    a.write()
    with pytest.raises((InvalidInput, Conflict, ScopeDenied)):
        await a.service.plan(1, a.s.value.file_id, a.s.actor, legacy_quiesced=True, task_archive=a.path, context=context())
    assert a.s.row()['process_task_id'] == 'old-task' and a.s.row()['ingestion_request'] is None


async def test_live_changed_or_expired_result_is_not_replayed_from_archive(archived):
    a = archived
    plan = await a.service.plan(1, a.s.value.file_id, a.s.actor, legacy_quiesced=True, task_archive=a.path, context=context())
    a.port.get.return_value = {**a.live, 'status': 'UNKNOWN', 'revision': '0'*64, 'result_present': False}
    with pytest.raises(Conflict): await a.service.admit(plan, a.s.actor, task_archive=a.path, context=context())
    assert a.s.row()['ingestion_request'] is None


async def test_edited_archive_invalidates_the_plan_before_admission(archived):
    a = archived
    plan = await a.service.plan(1, a.s.value.file_id, a.s.actor, legacy_quiesced=True, task_archive=a.path, context=context())
    a.path.write_bytes(a.path.read_bytes()+b'\n')
    with pytest.raises((InvalidInput, Conflict)):
        await a.service.admit(plan, a.s.actor, task_archive=a.path, context=context())
    assert a.s.row()['ingestion_request'] is None


async def test_ttl_countdown_does_not_change_archived_content_identity(archived):
    a = archived
    a.live['archive'][0]['ttl_ms'] = 4500
    plan = await a.service.plan(1, a.s.value.file_id, a.s.actor, legacy_quiesced=True, task_archive=a.path, context=context())
    assert plan.legacy_snapshot.task_references == {'process_task_id': 'old-task'}


async def test_auxiliary_key_change_rejects_admission_even_with_same_result(archived):
    a = archived
    plan = await a.service.plan(1, a.s.value.file_id, a.s.actor, legacy_quiesced=True, task_archive=a.path, context=context())
    a.live['archive'] = [*a.live['archive'], {'binding': 'general', 'key': 'progress:old-task', 'encoding': 'redis-dump',
        'ttl_ms': -1, 'value_base64': 'bmV3', 'sha256': hashlib.sha256(b'new').hexdigest()}]
    with pytest.raises(Conflict): await a.service.admit(plan, a.s.actor, task_archive=a.path, context=context())
    assert a.s.row()['ingestion_request'] is None


async def test_archive_does_not_suppress_other_source_findings(archived):
    a = archived
    source = a.m.source.page.side_effect
    def invalid(*args, **kwargs):
        page = source(*args, **kwargs)
        page.files[0].issues.append('SOURCE_HASH_MISMATCH')
        return page
    a.m.source.page.side_effect = invalid
    with pytest.raises(Conflict):
        await a.service.plan(1, a.s.value.file_id, a.s.actor, legacy_quiesced=True, task_archive=a.path, context=context())
    assert a.s.row()['ingestion_request'] is None


async def test_oversized_report_is_rejected_before_file_or_task_io(archived, monkeypatch):
    from management.services.knowledge_base import legacy_task_archive as module

    a = archived
    file = Mock()
    file.is_file.return_value = True
    file.stat.return_value = SimpleNamespace(st_size=1024 * 1024 * 1024 + 1)
    monkeypatch.setattr(module, 'Path', Mock(return_value=file))
    with pytest.raises(InvalidInput):
        await a.service.plan(1, a.s.value.file_id, a.s.actor, legacy_quiesced=True, task_archive=a.path, context=context())
    file.open.assert_not_called()
    a.port.get.assert_not_called()


async def test_task_scope_cannot_borrow_a_different_actor(archived):
    a = archived
    a.port.scope = StorageScope('management', 'tenant-a', 'owner', {LEGACY_TASKS})
    with pytest.raises(ScopeDenied):
        await a.service.plan(1, a.s.value.file_id, a.s.actor, legacy_quiesced=True, task_archive=a.path, context=context())
    a.port.get.assert_not_called()
