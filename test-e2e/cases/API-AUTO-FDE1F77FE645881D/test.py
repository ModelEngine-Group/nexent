from __future__ import annotations
import os
import uuid
import pytest
from shared.http import assert_status, client
from d3.assets import temporary_knowledge_base

CASE_ID = 'API-AUTO-FDE1F77FE645881D'
STAGE = 'D3'
CONFIG_SERVICE_NAME = 'nexent-config'
ACTIVE_STATUSES = ('UPLOADED', 'PROCESSING', 'FORWARDING')


def _batch_token():
    raw = os.environ.get('TEST_BATCH') or os.environ.get('TEST_RUN_ID') or uuid.uuid4().hex
    return raw[:32]


def _new_index_name():
    return f'kb-fde1f77-{_batch_token()}-{uuid.uuid4().hex[:8]}'


def _lifecycle(file_id):
    from database.knowledge_file_lifecycle_db import get_file_record
    return get_file_record(file_id=file_id, include_hidden=True)


async def _upload(api, index_name, docs):
    files = [('file', (name, content, 'text/plain')) for name, content in docs]
    response = await api.post(
        '/api/file/upload',
        data={'destination': 'minio', 'folder': 'knowledge_base', 'index_name': index_name},
        files=files,
    )
    assert_status(response, 200)
    records = response.json().get('file_records') or []
    assert records, 'upload returned no file_records'
    return records


def _process_body(index_name, entries):
    return {
        'files': entries,
        'index_name': index_name,
        'destination': 'minio',
        'chunking_strategy': 'basic',
    }


@pytest.mark.asyncio
@pytest.mark.stage(STAGE)
@pytest.mark.case_id(CASE_ID)
async def test_process_persists_parent_task_id(tenant_a_admin):
    identity = tenant_a_admin
    async with temporary_knowledge_base(identity, prefix='kb-parent-task') as knowledge:
        index_name = knowledge['index_name']
        async with client('config', token=identity.access_token) as api:
            legacy_name = f'legacy-{_batch_token()}.txt'
            legacy_records = await _upload(api, index_name, [(legacy_name, b'legacy single file content')])
            legacy = legacy_records[0]
            assert legacy.get('status') == 'UPLOADED'
            # upload_owner_service is an internal lifecycle field.  The upload
            # endpoint deliberately filters it from its response, so verify it
            # at the persistence layer instead of treating the API projection
            # as the database record.
            legacy_row = _lifecycle(legacy['file_id'])
            assert legacy_row is not None
            assert legacy_row.get('upload_owner_service') == CONFIG_SERVICE_NAME

            legacy_resp = await api.post('/api/file/process', json=_process_body(index_name, [{
                'path_or_url': legacy['object_name'],
                'filename': legacy_name,
                'file_id': legacy['file_id'],
            }]))
            assert_status(legacy_resp, 201)
            legacy_task_id = (legacy_resp.json().get('process_tasks') or {}).get('task_id')
            assert legacy_task_id
            legacy_row = _lifecycle(legacy['file_id'])
            assert legacy_row is not None
            assert legacy_row.get('parent_task_id') == legacy_task_id
            assert legacy_row.get('status') in ACTIVE_STATUSES

            batch_docs = [
                (f'batch-a-{_batch_token()}.txt', b'batch document a'),
                (f'batch-b-{_batch_token()}.txt', b'batch document b'),
            ]
            batch_records = await _upload(api, index_name, batch_docs)
            batch_entries = []
            for index, record in enumerate(batch_records):
                batch_entries.append({
                    'path_or_url': record['object_name'],
                    'filename': batch_docs[index][0],
                    'file_id': record['file_id'],
                })
            batch_resp = await api.post('/api/file/process', json=_process_body(index_name, batch_entries))
            assert_status(batch_resp, (200, 201))
            results = (batch_resp.json().get('process_tasks') or {}).get('results') or []
            submitted = {}
            for result in results:
                if result.get('status') == 'SUBMITTED':
                    submitted[result.get('file_id')] = result
            for record in batch_records:
                task = submitted.get(record['file_id'])
                rid = record['file_id']
                assert task is not None, f'file_id={rid} not SUBMITTED'
                row = _lifecycle(record['file_id'])
                assert row is not None
                assert row.get('parent_task_id') == task.get('task_id')
                assert row.get('parent_task_id')
                assert row.get('status') in ACTIVE_STATUSES

            mismatched = batch_records[0]
            before = _lifecycle(mismatched['file_id'])
            before_parent = before.get('parent_task_id') if before else None
            mismatched_resp = await api.post('/api/file/process', json=_process_body(index_name, [{
                'path_or_url': mismatched['object_name'],
                'filename': batch_docs[0][0],
                'file_id': uuid.uuid4().hex,
            }]))
            assert_status(mismatched_resp, (200, 201))
            after = _lifecycle(mismatched['file_id'])
            assert after is not None
            assert after.get('parent_task_id') == before_parent

            assert identity.access_token not in legacy_resp.text
            assert identity.access_token not in batch_resp.text
