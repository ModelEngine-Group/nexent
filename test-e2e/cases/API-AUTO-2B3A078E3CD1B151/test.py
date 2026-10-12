from __future__ import annotations

import asyncio
import json
import time
import uuid

import pytest

from shared.http import assert_status, client
from shared.factories.owned_lifecycle import register_knowledge, register_file, register_fence


def _run_id():
    return f'{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}'


def _decode(value):
    return value.decode('utf-8') if isinstance(value, bytes) else value


def _redis_service():
    from services.redis_service import get_redis_service

    return get_redis_service()


def _read_task_meta(task_id):
    raw = _redis_service().backend_client.get(f'celery-task-meta-{task_id}')
    if not raw:
        return None
    try:
        return json.loads(_decode(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


async def _wait_terminal(task_id, timeout_s=90.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        meta = _read_task_meta(task_id)
        if meta and meta.get('status') in {'SUCCESS', 'FAILURE'}:
            return meta
        await asyncio.sleep(0.5)
    raise TimeoutError(f'task {task_id} never reached terminal state within {timeout_s}s')


async def _chain_stages(cleanup_id):
    """Walk only this submitted chain backwards, never scan another run's tasks."""
    cleanup_meta = await _wait_terminal(cleanup_id)
    forward_id = cleanup_meta.get('parent_id')
    assert isinstance(forward_id, str) and forward_id != cleanup_id, 'cleanup task has no distinct forward parent'
    forward_meta = await _wait_terminal(forward_id)
    process_id = forward_meta.get('parent_id')
    assert isinstance(process_id, str) and process_id not in {cleanup_id, forward_id}, 'forward task has no distinct process parent'
    process_meta = await _wait_terminal(process_id)
    for meta in (cleanup_meta, forward_meta, process_meta):
        assert meta.get('status') == 'SUCCESS', 'delete-fence chain did not finish successfully'
        assert meta.get('root_id') in (None, process_id), 'task belongs to a different chain root'
    assert not process_meta.get('parent_id'), 'expected process root, found another parent'
    return process_id, process_meta, forward_id, forward_meta, cleanup_meta


def _embedding_model_name():
    from shared.config import model_by_type

    try:
        model = model_by_type('embedding')
    except Exception:
        return None
    return (
        model.get('modelName')
        or model.get('name')
        or model.get('display_name')
        or model.get('displayName')
        or None
    )


@pytest.mark.case_id('API-AUTO-2B3A078E3CD1B151')
@pytest.mark.stage('D3')
@pytest.mark.asyncio
async def test_delete_fence_cancels_process_forward_cleanup_chain(tenant_a_admin, monkeypatch):
    run_id = _run_id()
    tenant_id = tenant_a_admin.tenant_id
    index_name = f'kb-delete-fence-{run_id}'
    source = f'delete-fence-source-{run_id}.txt'
    file_id = uuid.uuid4().hex
    deleted_file_id = uuid.uuid4().hex

    from database.knowledge_db import create_knowledge_record, delete_knowledge_record
    from database.knowledge_file_lifecycle_db import create_file_record, delete_file_record

    redis_service = _redis_service()
    task_id = None
    forward_id = None
    cleanup_id = None
    knowledge_record_created = False
    file_record_created = False
    deleted_record_created = False

    try:
        kb = create_knowledge_record({
            'tenant_id': tenant_id,
            'index_name': index_name,
            'knowledge_name': f'delete-fence-{run_id}',
            'knowledge_describe': 'auto test resource',
            'embedding_model_name': _embedding_model_name(),
            'preserve_source_file': True,
        })
        knowledge_record_created = True
        register_knowledge(tenant_a_admin, kb)

        create_file_record(
            file_id=file_id,
            tenant_id=tenant_id,
            knowledge_id=kb['knowledge_id'],
            index_name=index_name,
            original_filename=source,
            status='UPLOADED',
            stage='UPLOAD',
        )
        file_record_created = True
        register_file(tenant_a_admin, index_name, kb['knowledge_id'], file_id)

        create_file_record(
            file_id=deleted_file_id,
            tenant_id=tenant_id,
            knowledge_id=kb['knowledge_id'],
            index_name=index_name,
            original_filename=f'deleted-{source}',
            status='DELETE_REQUESTED',
            stage='DELETE',
        )
        deleted_record_created = True
        register_file(tenant_a_admin, index_name, kb['knowledge_id'], deleted_file_id)

        register_fence(file_id)
        assert redis_service.mark_document_delete_requested(file_id=file_id) is True

        payload = {
            'source': source,
            'source_type': 'local',
            'chunking_strategy': 'basic',
            'index_name': index_name,
            'original_filename': source,
            'tenant_id': tenant_id,
            'file_id': file_id,
            'telemetry_context': {},
        }
        async with client('data_process', token=tenant_a_admin.access_token) as api:
            response = await api.post('/tasks', json=payload)
        assert_status(response, 201)
        cleanup_id = response.json()['task_id']
        assert cleanup_id
        task_id, process_meta, forward_id, forward_meta, cleanup_meta = await _chain_stages(cleanup_id)
        process_result = process_meta.get('result') or {}
        assert process_result.get('cancelled') is True
        assert process_result.get('chunks') is None
        assert 'Processing cancelled because document deletion was requested.' in str(process_result.get('message', ''))
        assert redis_service.backend_client.get(f'dp:{task_id}:chunks') is None

        forward_result = forward_meta.get('result') or {}
        assert forward_result.get('cancelled') is True, 'Forward lost cancellation; verify the deployed worker revision'
        assert forward_result.get('file_id') == file_id, 'Forward lost the owned document identity'
        assert forward_result.get('chunks_stored') == 0
        es_result = forward_result.get('es_result') or {}
        assert es_result.get('success') is False
        assert es_result.get('total_indexed') == 0
        assert 'Indexing cancelled because document was deleted.' in str(es_result.get('message', ''))

        cleanup_result = cleanup_meta.get('result') or {}
        source_cleanup = cleanup_result.get('source_cleanup') or {}
        assert source_cleanup.get('attempted') is False
        assert source_cleanup.get('skipped_reason') == 'document_delete_requested'

        from data_process.utils import is_document_delete_requested
        import database.knowledge_file_lifecycle_db as lifecycle_db
        import services.redis_service as redis_module

        class _RedisUnavailable:
            def is_document_delete_requested(self, **kwargs):
                raise RuntimeError('redis unavailable')

        # The shared helper imports Redis at the collaboration boundary. Patch
        # that supplier, not the obsolete private function in tasks.py.
        monkeypatch.setattr(redis_module, 'get_redis_service', lambda: _RedisUnavailable())

        assert is_document_delete_requested(
            index_name=index_name,
            source=source,
            file_id=deleted_file_id,
            tenant_id=tenant_id,
        ) is True

        assert is_document_delete_requested(
            index_name=index_name,
            source=source,
            file_id=uuid.uuid4().hex,
            tenant_id=tenant_id,
        ) is False

        def _raise_lifecycle(**kwargs):
            raise RuntimeError('lifecycle query failed')

        monkeypatch.setattr(lifecycle_db, 'get_file_record', _raise_lifecycle)
        assert is_document_delete_requested(
            index_name=index_name,
            source=source,
            file_id=deleted_file_id,
            tenant_id=tenant_id,
        ) is False
    finally:
        try:
            redis_service.clear_document_delete_fence(file_id=file_id)
            redis_service.clear_document_delete_fence(file_id=deleted_file_id)
        except Exception:
            pass
        if file_record_created:
            try:
                delete_file_record(file_id)
            except Exception:
                pass
        if deleted_record_created:
            try:
                delete_file_record(deleted_file_id)
            except Exception:
                pass
        if knowledge_record_created:
            try:
                delete_knowledge_record({'index_name': index_name, 'user_id': tenant_a_admin.user_id})
            except Exception:
                pass
        for tid in (task_id, forward_id, cleanup_id):
            if tid:
                try:
                    redis_service._cleanup_single_task_related_keys(tid)
                except Exception:
                    pass
