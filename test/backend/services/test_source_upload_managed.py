# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Upload timeouts retain uncertainty and never create an implicit worker manager."""

from unittest.mock import AsyncMock

import pytest
from management.services.file import source_upload
from nexent.storage.errors import OutcomeUnknown


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
