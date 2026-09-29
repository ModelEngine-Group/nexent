from __future__ import annotations

import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import inspect

from shared.auth import sign_in
from shared.config import load_yaml
from shared.http import assert_status, client
from shared.factories.case_resources import cleanup_case, register_http


def _asset_owner_enabled() -> bool:
    """Asset-owner cases need accounts that only exist when the feature is on."""
    for name in ('NEXENT_FEATURE_ASSET_OWNER',):
        if name in os.environ:
            return str(os.environ[name]).strip().lower() in {'1', 'true', 'yes', 'on', 'enabled'}
    features = load_yaml('environment.yaml').get('features') or {}
    return bool(features.get('asset_owner'))


if not _asset_owner_enabled():
    pytest.skip(
        'SKIPPED_BY_POLICY: asset-owner case requires features.asset_owner=true; '
        'anchor preparation only creates asset_owner_admin when the feature is enabled',
        allow_module_level=True,
    )


CASE_ID = 'API-AUTO-877981976E0A978F'
NORTHBOUND_SERVICE = 'nexent-northbound'
CONFIG_SERVICE = 'nexent-config'
SCHEMA = 'nexent'


@pytest_asyncio.fixture(scope='session')
async def asset_owner():
    return await sign_in('asset_owner_admin')


@pytest_asyncio.fixture(scope='session')
async def asset_owner_northbound_key(asset_owner):
    async with client('config', token=asset_owner.access_token) as api:
        created = await api.post('/user/tokens')
        assert_status(created, 200)
        payload = created.json().get('data') or created.json()
        token_id = payload.get('token_id') or payload.get('id')
        secret = payload.get('access_key') or payload.get('token')
        if token_id:
            register_http(asset_owner, CASE_ID, 'owned_identity_tokens', token_id, f'/user/tokens/{token_id}')
        if not token_id or not secret:
            raise AssertionError('asset-owner token creation did not return token_id and access_key')
    try:
        yield str(secret)
    finally:
        async with client('config', token=asset_owner.access_token) as api:
            deleted = await api.delete(f'/user/tokens/{token_id}')
            assert_status(deleted, (200, 404))


@pytest_asyncio.fixture
async def owned_lifecycle_cleanup():
    async with cleanup_case(CASE_ID):
        yield


def _embedding_model_id(identity):
    from database.model_management_db import get_model_records

    # The northbound create endpoint resolves the model inside the caller's
    # tenant (asset-owner tenant), so a system-tenant model id is rejected with
    # "Embedding model with id N not found".  The anchor provisions the
    # asset-owner anchor models for exactly this lookup.
    records = get_model_records({'model_type': 'embedding'}, tenant_id=identity.tenant_id)
    if not records:
        return None
    return int(records[0]['model_id'])


def _set_uploading_older_than(file_id: str, cutoff: datetime) -> None:
    from database.client import get_db_session
    from database.db_models import KnowledgeFileLifecycle

    with get_db_session() as session:
        row = (
            session.query(KnowledgeFileLifecycle)
            .filter(KnowledgeFileLifecycle.file_id == file_id)
            .with_for_update()
            .first()
        )
        assert row is not None, f'lifecycle row missing for file_id={file_id}'
        row.status = 'UPLOADING'
        row.delete_flag = 'N'
        row.create_time = cutoff - timedelta(hours=1)
        session.flush()


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
async def test_upload_owner_service_isolation(owned_lifecycle_cleanup, asset_owner, asset_owner_northbound_key):
    from database.client import db_client
    from database.db_models import KnowledgeFileLifecycle
    from database.knowledge_file_lifecycle_db import (
        delete_file_record,
        get_file_record,
        list_file_records,
        list_uploading_files_created_before,
    )

    columns = {c.name for c in KnowledgeFileLifecycle.__table__.columns}
    assert 'upload_owner_service' in columns

    inspector = inspect(db_client.engine)
    indexes = inspector.get_indexes(KnowledgeFileLifecycle.__tablename__, schema=SCHEMA)
    index_names = {ix['name'] for ix in indexes}
    assert 'idx_knowledge_file_lifecycle_upload_recovery' in index_names

    run_id = str(uuid4()).replace('-', '')[:12]
    index_name = f'kb-{run_id}'

    embedding_model_id = _embedding_model_id(asset_owner)
    body = {'embedding_model_id': embedding_model_id} if embedding_model_id else None

    async with client('northbound', api_key=asset_owner_northbound_key) as nb:
        created = await nb.post(f'/nb/v1/knowledge/indices/{index_name}', json=body)
        assert_status(created, (200, 201))
        created_body = created.json()
        # ``POST /nb/v1/knowledge/indices/{name}`` takes the display name and the
        # service generates the internal index name.  The upload endpoints (and
        # the config-service upload, which resolves the name against
        # knowledge_t) take that internal name; a display name answers 404.
        internal_name = str(created_body.get('id') or created_body.get('index_name') or '')
        if not internal_name:
            from shared.factories.knowledge import register_partial_knowledge
            register_partial_knowledge(asset_owner, index_name, owner=CASE_ID, role=index_name)
            raise AssertionError('northbound KB creation omitted its internal index ID')
        register_http(asset_owner, CASE_ID, 'owned_knowledge', internal_name, f'/indices/{internal_name}')

        filename_a = f'file-a-{run_id}.txt'
        upload_a = await nb.post(
            '/nb/v1/knowledge/file/upload',
            data={'index_name': internal_name},
            files={'file': (filename_a, b'northbound upload payload', 'text/plain')},
        )
        assert_status(upload_a, 201)
        payload_a = upload_a.json()
        assert filename_a in payload_a.get('uploaded_filenames', [])
        object_name_a = payload_a.get('uploaded_file_paths', [None])[0]

    async with client('config', token=asset_owner.access_token) as cfg:
        filename_b = f'file-b-{run_id}.txt'
        upload_b = await cfg.post(
            '/file/upload',
            data={'destination': 'minio', 'index_name': internal_name},
            files={'file': (filename_b, b'config upload payload', 'text/plain')},
        )
        assert_status(upload_b, 200)
        payload_b = upload_b.json()
        records_b = payload_b.get('file_records', [])
        assert records_b, 'config upload returned no file_records'

    all_rows = list_file_records(index_name=internal_name)
    row_a = next((r for r in all_rows if r.get('object_name') == object_name_a), None)
    row_b = get_file_record(file_id=records_b[0].get('file_id'), index_name=internal_name)
    assert row_a is not None, 'northbound upload did not persist a lifecycle row'
    assert row_b is not None, 'config upload did not persist a lifecycle row'

    assert row_a.get('upload_owner_service') == NORTHBOUND_SERVICE
    assert row_a.get('status') in ('UPLOADING', 'UPLOADED', 'PROCESSING', 'FORWARDING', 'FAILED', 'COMPLETED')
    assert row_b.get('upload_owner_service') == CONFIG_SERVICE
    assert row_a.get('upload_owner_service') != row_b.get('upload_owner_service')

    cutoff = datetime.utcnow()
    _set_uploading_older_than(row_a['file_id'], cutoff)
    _set_uploading_older_than(row_b['file_id'], cutoff)

    northbound_rows = list_uploading_files_created_before(cutoff, NORTHBOUND_SERVICE)
    config_rows = list_uploading_files_created_before(cutoff, CONFIG_SERVICE)

    northbound_ids = {r['file_id'] for r in northbound_rows}
    config_ids = {r['file_id'] for r in config_rows}

    assert row_a['file_id'] in northbound_ids
    assert row_b['file_id'] not in northbound_ids
    assert row_b['file_id'] in config_ids
    assert row_a['file_id'] not in config_ids

    with pytest.raises(ValueError):
        list_uploading_files_created_before(cutoff, '')

    assert asset_owner_northbound_key not in str(payload_a)
    assert asset_owner.access_token not in str(payload_a)
    assert asset_owner_northbound_key not in str(payload_b)
    assert asset_owner.access_token not in str(payload_b)

    # The fixture removes the owned KB through the product API, including files.
    # Do not delete lifecycle rows first: that would discard object/task cleanup metadata.
