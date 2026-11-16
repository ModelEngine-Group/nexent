# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Upload timeouts retain uncertainty and never create an implicit worker manager."""

from threading import Event
from unittest.mock import AsyncMock, Mock

import pytest
from management.services.file import source_upload
from nexent.storage.errors import OutcomeUnknown, Unavailable


@pytest.mark.asyncio
async def test_managed_timeout_is_not_reported_as_definite_upload_failure():
    manager = AsyncMock()
    manager.run.side_effect = TimeoutError()
    with pytest.raises(OutcomeUnknown):
        await source_upload.upload_knowledge_source(
            {"file_id": "a" * 32}, b"source", "text/plain", manager=manager
        )
    assert manager.run.call_args.args[0] == "file-upload"
    spec = manager.run.call_args.args[1]
    assert spec.pass_cancel_event and spec.deadline_monotonic is not None


@pytest.mark.asyncio
async def test_no_service_manager_refuses_before_io(mocker):
    mocker.patch.object(source_upload, "get_current_thread_manager", return_value=None)
    mocker.patch.object(source_upload, "get_default_thread_manager", return_value=None)
    ports = mocker.patch.object(source_upload, "source_upload_ports")
    with pytest.raises(RuntimeError, match="service-owned"):
        await source_upload.upload_knowledge_source({}, b"source", "text/plain")
    ports.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, Unavailable, RuntimeError])
async def test_managed_upload_accounts_before_returning_snapshot(mocker, failure):
    record = {
        "file_id": "a" * 32,
        "version": 0,
        "created_by": "user-a",
        "upload_owner_service": "management",
        "status": "UPLOADING",
    }
    records, objects, source = Mock(), Mock(), Mock()
    ports = mocker.patch.object(source_upload, "source_upload_ports")
    ports.return_value.__enter__.return_value = records, objects
    publisher = mocker.patch.object(source_upload, "SourcePublisher").return_value
    publisher.publish.return_value = source
    finalizer = mocker.patch.object(source_upload, "SourceFinalizer").return_value
    finalizer.account.return_value = {
        **record,
        "version": 3,
        "stage": "SOURCE_ACCOUNTED",
        "storage_object_id": 7,
    }
    if failure:
        finalizer.account.side_effect = failure()
    manager = Mock(run=AsyncMock(side_effect=lambda _lane, _spec, work: work(Event())))
    if failure:
        with pytest.raises(OutcomeUnknown):
            await source_upload.upload_knowledge_source(
                record, b"source", "text/plain", manager=manager
            )
        assert "storage_object_id" not in record and record["version"] == 0
    else:
        assert (
            await source_upload.upload_knowledge_source(
                record, b"source", "text/plain", manager=manager
            )
            is source
        )
        assert record["storage_object_id"] == 7 and record["version"] == 3
    finalizer.account.assert_called_once()
    assert finalizer.account.call_args.kwargs["owner_user_id"] == "user-a"
