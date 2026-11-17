# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only a reserved target can consume staged bytes through the existing uploader."""

import io
from tempfile import SpooledTemporaryFile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.file import UploadFilesResult
from management.services.file import staged_local_binding as module
from nexent.storage.errors import OutcomeUnknown

from test.backend.services.test_local_source_staging import context


@pytest.mark.asyncio
async def test_binding_uses_fixed_file_identity_and_confirms_alias_after_upload(
    monkeypatch,
):
    stage = {
        "stage_id": "a" * 32,
        "bound_file_id": "b" * 32,
        "original_filename": "a.txt",
        "file_size": 4,
    }
    actor = SimpleNamespace(user_id="u", tenant_id="t")
    stream = SpooledTemporaryFile(max_size=5)  # noqa: SIM115 - The callee owns and closes this stream.
    stream.write(b"data")
    stream.seek(0)
    read = Mock(return_value=stream)
    finish = Mock(return_value={"file_id": "b" * 32})
    monkeypatch.setattr(module, "open_staged_local_source", read)
    monkeypatch.setattr(module, "finish_staged_binding", finish)

    async def blocking(name, call, *args, **kwargs):
        return call(*args)

    monkeypatch.setattr(module, "run_blocking", blocking)

    async def upload(**kwargs):
        assert kwargs["lifecycle_file_ids"] == [stage["bound_file_id"]]
        assert kwargs["destination"] == "minio" and kwargs["index_name"] == "kb"
        assert (kwargs["user_id"], kwargs["uploader_tenant_id"]) == ("u", "t")
        assert await kwargs["file"][0].read() == b"data"
        return UploadFilesResult(
            [], ["key"], ["a.txt"], file_records=[{"file_id": "b" * 32}]
        )

    uploader = AsyncMock(side_effect=upload)
    row = await module.publish_staged_binding(
        stage, "kb", actor, "/owned", context(), uploader=uploader
    )
    assert row["file_id"] == "b" * 32 and uploader.await_count == 1
    assert finish.call_count == 1 and stream.closed


@pytest.mark.asyncio
async def test_unknown_upload_does_not_confirm_or_replay(monkeypatch):
    stage = {
        "stage_id": "a" * 32,
        "bound_file_id": "b" * 32,
        "original_filename": "a.txt",
        "file_size": 4,
    }
    stream = io.BytesIO(b"data")
    monkeypatch.setattr(module, "open_staged_local_source", Mock(return_value=stream))
    finish = Mock()
    monkeypatch.setattr(module, "finish_staged_binding", finish)

    async def blocking(name, call, *args, **kwargs):
        return call(*args)

    monkeypatch.setattr(module, "run_blocking", blocking)
    uploader = AsyncMock(side_effect=OutcomeUnknown())
    with pytest.raises(OutcomeUnknown):
        await module.publish_staged_binding(
            stage,
            "kb",
            SimpleNamespace(user_id="u", tenant_id="t"),
            "/owned",
            context(),
            uploader=uploader,
        )
    assert uploader.await_count == 1 and not finish.called and stream.closed
