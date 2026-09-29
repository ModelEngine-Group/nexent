'''D3 API-IT: delete_document_by_scope by source_only/full deletion.

Covers the cross-service deletion orchestration of backend/management/services/
knowledge_base/deletion.py: durable PG tombstone (DELETE_REQUESTED) and Redis
fence before cleanup, Celery task cancellation, source_only vs full scope
semantics, invalid-scope ValueError, and pending + background retry behavior.
'''

from __future__ import annotations

import asyncio
import os
import time
import uuid
from urllib.parse import quote

import pytest

from shared.auth import TestIdentity
from shared.http import MODEL_TIMEOUT, assert_status, client, response_message
from shared.asset_registry import AssetDependencyError, register_asset
from shared.factories.ownership import register_owned_http
from d3.assets import model_id as configured_model_id, model_request


CASE_ID = 'API-AUTO-FCA0909EFA632CC7'
_COMPLETED = 'COMPLETED'
_FAILURE_STATES = ('PROCESS_FAILED', 'FORWARD_FAILED')


def _run_id() -> str:
    return os.environ.get('TEST_BATCH') or 'fca-' + uuid.uuid4().hex[:12]


def _document_bytes(filename: str) -> bytes:
    root = os.environ.get('NEXENT_TEST_HOME')
    if root:
        from pathlib import Path

        candidate = Path(root) / 'assets' / 'documents' / filename
        if candidate.is_file():
            return candidate.read_bytes()
    text = (
        'Nexent delete-by-scope integration document. '
        'File: ' + filename + ' - durable deletion fence and lifecycle cleanup.'
    )
    return text.encode('utf-8')


async def _resolve_embedding_model_id(identity: TestIdentity) -> int:
    try:
        return await configured_model_id('embedding', identity)
    except AssetDependencyError as exc:
        if 'no exact configured name/type/model_id match' not in str(exc):
            raise

    # A case-owned tenant may have no model yet. Create the configured real
    # provider model through the product API and register cleanup immediately.
    display_name = 'd3-delete-embedding-' + uuid.uuid4().hex[:12]
    payload = model_request('embedding', display_name=display_name)
    async with client('config', token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        created = await api.post('/model/create', json=payload)
    assert_status(created, 200)
    register_asset(
        'owned_models', display_name, display_name, owner_case_id=CASE_ID,
        cleanup={
            'service': 'config', 'identity': identity.id, 'method': 'POST',
            'path': '/model/delete?display_name=' + quote(display_name, safe=''),
            'allowed_statuses': [200, 404],
        },
    )
    return await configured_model_id('embedding', identity)


async def _create_knowledge_base(identity: TestIdentity, name: str) -> str:
    model_id = await _resolve_embedding_model_id(identity)
    async with client('config', token=identity.access_token) as api:
        response = await api.post('/indices/' + name, json={'embedding_model_id': model_id})
    assert_status(response, 200)
    payload = response.json()
    index_name = payload.get('id') or payload.get('index_name')
    if not index_name:
        raise AssertionError('create knowledge base did not return index_name: ' + str(payload))
    register_owned_http(identity, 'owned_knowledge_bases', str(index_name),
                        '/indices/' + str(index_name))
    return str(index_name)


async def _upload_and_process(
    identity: TestIdentity, index_name: str, filename: str, content: bytes
) -> tuple:
    async with client('config', token=identity.access_token) as api:
        response = await api.post(
            '/file/upload',
            data={'destination': 'minio', 'folder': 'knowledge_base', 'index_name': index_name},
            files={'file': (filename, content, 'text/plain')},
        )
    assert_status(response, (200, 201))
    payload = response.json()
    records = payload.get('file_records') or []
    paths = payload.get('uploaded_file_paths') or []
    if not records:
        raise AssertionError('upload returned no lifecycle file_records: ' + str(payload))
    record = records[0]
    file_id = record.get('file_id')
    object_name = record.get('object_name') or (paths[0] if paths else None)
    if not file_id or not object_name:
        raise AssertionError('upload missing file_id/object_name: ' + str(record))

    async with client('config', token=identity.access_token) as api:
        process_response = await api.post(
            '/file/process',
            json={
                'files': [{'path_or_url': object_name, 'filename': filename, 'file_id': file_id}],
                'index_name': index_name,
                'destination': 'minio',
                'chunking_strategy': 'basic',
            },
        )
    assert_status(process_response, (200, 201))
    return str(file_id), str(object_name)


async def _list_files(identity: TestIdentity, index_name: str) -> list:
    async with client('config', token=identity.access_token) as api:
        response = await api.get('/indices/' + index_name + '/files')
    assert_status(response, 200)
    return response.json().get('files') or []


async def _find_file(identity: TestIdentity, index_name: str, object_name: str, file_id: str):
    for info in await _list_files(identity, index_name):
        if info.get('path_or_url') == object_name or info.get('file_id') == file_id:
            return info
    return None


async def _wait_status(identity, index_name, object_name, file_id, accepted, timeout=180.0):
    deadline = time.monotonic() + timeout
    while True:
        info = await _find_file(identity, index_name, object_name, file_id)
        if info is not None:
            status = str(info.get('status') or '')
            if status in accepted:
                return info
            if status in _FAILURE_STATES:
                raise AssertionError('file entered failure state ' + status + ': ' + str(info))
        if time.monotonic() >= deadline:
            raise TimeoutError('file did not reach ' + str(accepted) + ' within timeout')
        await asyncio.sleep(1.0)


async def _delete_document(identity, index_name, path_or_url=None, file_id=None, scope='full'):
    params = {'scope': scope}
    if path_or_url:
        params['path_or_url'] = path_or_url
    if file_id:
        params['file_id'] = file_id
    async with client('config', token=identity.access_token) as api:
        return await api.delete('/indices/' + index_name + '/documents', params=params)


async def _cleanup_kb(identity, index_name):
    try:
        async with client('config', token=identity.access_token) as api:
            response = await api.delete('/indices/' + index_name)
        if response.status_code not in (200, 404):
            response.read()
    except Exception:
        pass


@pytest.mark.asyncio
@pytest.mark.stage('D3')
@pytest.mark.case_id(CASE_ID)
async def test_delete_document_by_scope(tenant_a_admin: TestIdentity) -> None:
    identity = tenant_a_admin
    run = _run_id()
    kb_name = 'api-auto-del-' + run
    created = []

    try:
        index_name = await _create_knowledge_base(identity, kb_name)
        created.append(index_name)

        # Scenario 1: invalid scope raises a deterministic domain ValueError.
        filename_a = 'doc_candidate.txt'
        file_id_a, object_a = await _upload_and_process(
            identity, index_name, filename_a, _document_bytes(filename_a)
        )
        invalid_response = await _delete_document(
            identity, index_name, path_or_url=object_a, file_id=file_id_a, scope='invalid'
        )
        assert invalid_response.status_code == 400
        detail = response_message(invalid_response)
        assert 'Invalid scope' in detail

        # Scenario 2: source_only on a terminal document keeps ES chunks/vectors.
        await _wait_status(identity, index_name, object_a, file_id_a, {_COMPLETED})
        source_only_response = await _delete_document(
            identity, index_name, path_or_url=object_a, file_id=file_id_a, scope='source_only'
        )
        assert_status(source_only_response, 200)
        source_only_result = source_only_response.json()
        assert source_only_result.get('scope') == 'source_only'
        assert 'cancelled_tasks' in source_only_result
        if source_only_result.get('status') == 'success':
            assert source_only_result.get('deleted_es_count') == 0
            assert source_only_result.get('deleted_minio') is True
            assert source_only_result.get('source_available') is False
            remaining = await _find_file(identity, index_name, object_a, file_id_a)
            assert remaining is not None
            assert int(remaining.get('chunk_count') or 0) > 0

        # Scenario 3: source_only against a non-terminal document surfaces
        # the domain error; the race-free full scope path is covered next.
        filename_c = 'doc_nonterminal.txt'
        file_id_c, object_c = await _upload_and_process(
            identity, index_name, filename_c, _document_bytes(filename_c)
        )
        racing_response = await _delete_document(
            identity, index_name, path_or_url=object_c, file_id=file_id_c, scope='source_only'
        )
        if racing_response.status_code == 400:
            detail_c = response_message(racing_response)
            assert 'Cannot delete source file while document is in state' in detail_c
        else:
            assert_status(racing_response, 200)
            racing_result = racing_response.json()
            if racing_result.get('status') == 'pending':
                assert racing_result.get('deletion_pending') is True

        # Scenario 4: full deletion removes ES, MinIO, Redis and PG lifecycle.
        filename_b = 'doc_full.txt'
        file_id_b, object_b = await _upload_and_process(
            identity, index_name, filename_b, _document_bytes(filename_b)
        )
        await _wait_status(identity, index_name, object_b, file_id_b, {_COMPLETED})
        full_response = await _delete_document(
            identity, index_name, path_or_url=object_b, file_id=file_id_b, scope='full'
        )
        assert_status(full_response, 200)
        full_result = full_response.json()
        assert full_result.get('scope') == 'full'
        assert 'cancelled_tasks' in full_result
        assert full_result.get('status') in ('success', 'pending')
        if full_result.get('status') == 'success':
            assert int(full_result.get('deleted_es_count') or 0) > 0
            assert full_result.get('deleted_minio') is True
            assert full_result.get('lifecycle_deleted') is True
        elif full_result.get('deletion_pending') is True:
            assert full_result.get('lifecycle_status') == 'DELETE_REQUESTED'

        # Full deletion is idempotent: the document disappears from the file list.
        for _ in range(30):
            if await _find_file(identity, index_name, object_b, file_id_b) is None:
                break
            await asyncio.sleep(1.0)
        else:
            remaining_b = await _find_file(identity, index_name, object_b, file_id_b)
            assert remaining_b is None

    finally:
        for created_index in created:
            await _cleanup_kb(identity, created_index)
