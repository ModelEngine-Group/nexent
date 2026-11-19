# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve ordinary/Northbound upload failure envelopes without duplicate ERROR."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from management.api import northbound
from management.api.file import file_management
from nexent.storage.errors import DeadlineExceeded


@pytest.mark.parametrize('error', [DeadlineExceeded(), TimeoutError()])
async def test_ordinary_upload_deadline_preserves_error_envelope(mocker, caplog, error):
    mocker.patch.object(file_management, 'get_current_user_id', return_value=('u', 't'))
    mocker.patch.object(file_management, 'require_knowledge_base_edit_permission')
    upload = mocker.patch.object(file_management, 'upload_files_impl', new=AsyncMock(side_effect=error))
    result = await file_management.upload_files(Mock(), [Mock()], 'minio', 'knowledge_base', 'kb', None)
    assert result.status_code == 500 and json.loads(result.body) == {'message': 'File upload error.'}
    assert upload.await_count == 1 and upload.await_args.kwargs['uploader_tenant_id'] == 't'
    assert not any(record.levelname == 'ERROR' for record in caplog.records)


@pytest.mark.parametrize('error', [DeadlineExceeded(), TimeoutError()])
async def test_northbound_upload_deadline_preserves_error_envelope(mocker, caplog, error):
    mocker.patch.object(northbound, '_require_asset_owner_context', new=AsyncMock(return_value=SimpleNamespace(user_id='u', tenant_id='t')))
    upload = mocker.patch.object(northbound, 'upload_files_impl', new=AsyncMock(side_effect=error))
    result = await northbound.upload_files(Mock(), [Mock()], 'kb')
    assert result.status_code == 500 and json.loads(result.body) == {'message': 'File upload error.'}
    assert upload.await_count == 1 and upload.await_args.kwargs['uploader_tenant_id'] == 't'
    assert not any(record.levelname == 'ERROR' for record in caplog.records)
