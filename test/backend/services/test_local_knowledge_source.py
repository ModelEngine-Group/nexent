# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local KB mirrors retain pinned object ownership and never accept caller-controlled server paths."""

import hashlib
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.file import UploadFilesResult
from management.services.file.local_knowledge_source import upload_local_knowledge_files
from nexent.storage.errors import OutcomeUnknown


@pytest.mark.asyncio
async def test_local_wrapper_preserves_success_order_and_original_source_records(
    monkeypatch, tmp_path
):
    from management.services.file import local_knowledge_source as module

    uploads = [
        SimpleNamespace(file=io.BytesIO(b"a")),
        SimpleNamespace(file=io.BytesIO(b"b")),
    ]
    rows = [
        {"file_id": c * 32, "object_name": "kb/" + c, "original_filename": c + ".txt"}
        for c in ("a", "b")
    ]
    result = UploadFilesResult(
        ["first failed"], ["kb/b"], ["b.txt"], {"remaining": 4}, rows
    )
    uploader = AsyncMock(return_value=result)
    observed = []

    async def blocking(name, fn, record, stream, actor, root, context, *, lane, owner):
        assert lane == "file-upload"
        observed.append((record["file_id"], stream.read()))
        return {
            **record,
            "local_source_path": str(tmp_path / record["file_id"] / "b.txt"),
        }

    monkeypatch.setattr(module, "run_blocking", blocking)
    output = await upload_local_knowledge_files(
        uploads,
        uploader=uploader,
        actor=SimpleNamespace(user_id="u", tenant_id="t"),
        root=tmp_path,
    )
    assert observed == [("b" * 32, b"b")]
    assert output[0] == ["first failed"] and output[2] == ["b.txt"]
    assert output[1] == [str(tmp_path / ("b" * 32) / "b.txt")]
    assert output.quota_status == {"remaining": 4}
    assert output.file_records[1]["object_name"] == "kb/b"
    uploader.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_local_registration_retains_object_identity_without_another_upload(
    monkeypatch, tmp_path
):
    from management.services.file import local_knowledge_source as module

    row = {"file_id": "a" * 32, "object_name": "kb/a", "original_filename": "a.txt"}
    uploader = AsyncMock(
        return_value=UploadFilesResult([], ["kb/a"], ["a.txt"], file_records=[row])
    )
    monkeypatch.setattr(module, "run_blocking", AsyncMock(side_effect=OutcomeUnknown()))
    result = await upload_local_knowledge_files(
        [SimpleNamespace(file=io.BytesIO(b"a"))],
        uploader=uploader,
        actor=SimpleNamespace(user_id="u", tenant_id="t"),
        root=tmp_path,
    )
    assert not result[1] and result[0] == [
        "Local source publication requires reconciliation"
    ]
    assert result.file_records == [row]
    uploader.assert_awaited_once()


def test_local_copy_is_exclusive_hash_checked_and_confined(tmp_path):
    from nexent.storage.errors import Conflict, ScopeDenied

    from infrastructure.file_processing.local_source import copy_local_source
    from test.backend.services.test_cleanse_jobs import context

    path = copy_local_source(
        io.BytesIO(b"abc"),
        tmp_path,
        "a" * 32,
        "file.txt",
        expected_size=3,
        expected_sha256=hashlib.sha256(b"abc").hexdigest(),
        context=context(),
    )
    assert path.read_bytes() == b"abc" and path.is_relative_to(tmp_path)
    with pytest.raises(Conflict):
        copy_local_source(
            io.BytesIO(b"other"),
            tmp_path,
            "a" * 32,
            "file.txt",
            expected_size=5,
            expected_sha256=hashlib.sha256(b"other").hexdigest(),
            context=context(),
        )
    assert path.read_bytes() == b"abc"
    with pytest.raises(ScopeDenied):
        copy_local_source(
            io.BytesIO(b"abc"),
            tmp_path,
            "../private",
            "file.txt",
            expected_size=3,
            expected_sha256=hashlib.sha256(b"abc").hexdigest(),
            context=context(),
        )


def test_wrong_local_hash_removes_only_the_new_partial_copy(tmp_path):
    from nexent.storage.errors import Conflict

    from infrastructure.file_processing.local_source import copy_local_source
    from test.backend.services.test_cleanse_jobs import context

    other = tmp_path / "unrelated.txt"
    other.write_bytes(b"keep")
    with pytest.raises(Conflict):
        copy_local_source(
            io.BytesIO(b"abc"),
            tmp_path,
            "b" * 32,
            "file.txt",
            expected_size=3,
            expected_sha256="a" * 64,
            context=context(),
        )
    assert other.read_bytes() == b"keep"
    assert not (tmp_path / "knowledge" / ("b" * 32)).exists()
