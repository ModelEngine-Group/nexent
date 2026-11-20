# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""FILE-BODY-04 keeps the existing Northbound download contract and authorization."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.constants.constants import (
    ASSET_OWNER_TENANT_ID,
    RATE_LIMIT_EXCEEDED_DETAIL,
)
from contracts.errors.exceptions import ManagementReadBusyError
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from management.api import northbound
from nexent.storage.errors import DeadlineExceeded


@pytest.fixture
def api(mocker):
    context = SimpleNamespace(user_id='publisher', tenant_id=ASSET_OWNER_TENANT_ID)
    mocker.patch.object(northbound, '_require_asset_owner_context', new_callable=AsyncMock, return_value=context)
    permission = mocker.patch.object(northbound, 'check_file_access', return_value=True)
    read = mocker.patch.object(northbound, 'read_download', new_callable=AsyncMock, return_value=(b'owned', 'text/plain'))
    app = FastAPI()
    app.include_router(northbound.router)
    with TestClient(app) as client:
        yield client, read, permission


def test_stream_keeps_content_disposition_cache_and_etag(api):
    client, read, permission = api
    response = client.get('/nb/v1/knowledge/file/download/knowledge_base/source.txt?download=stream')
    assert response.status_code == 200 and response.content == b'owned'
    assert response.headers['etag'] == '"knowledge_base/source.txt"'
    assert response.headers['cache-control'] == 'public, max-age=3600'
    assert 'source.txt' in response.headers['content-disposition']
    permission.assert_called_once_with('knowledge_base/source.txt', 'publisher', ASSET_OWNER_TENANT_ID)
    assert read.await_args.args[0] == 'knowledge_base/source.txt'


def test_base64_keeps_all_fields(api):
    client, _, _ = api
    response = client.get('/nb/v1/knowledge/file/download/knowledge_base/source.txt?download=base64')
    assert response.status_code == 200
    assert response.json() == {'success': True, 'base64': 'b3duZWQ=', 'content_type': 'text/plain',
                               'object_name': 'knowledge_base/source.txt'}


def test_rejected_permission_never_reads(api):
    client, read, permission = api
    permission.return_value = False
    assert client.get('/nb/v1/knowledge/file/download/knowledge_base/source.txt?download=stream').status_code == 403
    read.assert_not_awaited()


def test_rejected_identity_never_reads(api, mocker):
    client, read, _ = api
    mocker.patch.object(northbound, '_require_asset_owner_context', new_callable=AsyncMock, side_effect=HTTPException(403))
    assert client.get('/nb/v1/knowledge/file/download/knowledge_base/source.txt?download=stream').status_code == 403
    read.assert_not_awaited()


def test_busy_uses_existing_northbound_rate_limit_shape(api):
    client, read, _ = api
    read.side_effect = ManagementReadBusyError()
    response = client.get('/nb/v1/knowledge/file/download/knowledge_base/source.txt?download=stream')
    assert response.status_code == 429 and response.json() == {'detail': RATE_LIMIT_EXCEEDED_DETAIL}
    assert response.headers['retry-after'] == '1'


def test_reported_deadline_has_no_duplicate_error(api, caplog):
    client, read, _ = api
    read.side_effect = DeadlineExceeded()
    response = client.get('/nb/v1/knowledge/file/download/knowledge_base/source.txt?download=stream')
    assert response.status_code == 500 and response.json() == {'message': 'Failed to get file.'}
    assert not [r for r in caplog.records if r.levelname == 'ERROR']
