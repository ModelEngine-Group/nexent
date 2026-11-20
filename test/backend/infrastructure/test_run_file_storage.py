# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ReadTimeoutError
from nexent.storage.errors import ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.object_storage import run_files


@pytest.fixture
def storage(monkeypatch):
    provider = Mock()
    factory = Mock(return_value=provider)
    monkeypatch.setattr(run_files, "_configured_environment", lambda: SimpleNamespace(MINIO_DEFAULT_BUCKET="files"))
    monkeypatch.setattr(run_files, "_configured_client", factory)
    return run_files.RunFileStorage(ServicePrincipal("reader", "tenant-a"), "run-a"), provider, factory


def test_workspace_file_download_and_upload_use_exact_keys(storage, tmp_path):
    files, provider, _ = storage
    original = b"owned document"
    source = "attachments/reader/input.txt"
    target = "workspace/reader/run-a/outputs/subdirectory/output.txt"
    body = BytesIO(original)
    provider.head_object.return_value = {"ContentLength": len(original), "ETag": '"source"'}
    provider.get_object.return_value = {"Body": body}
    provider.put_object.side_effect = lambda **kwargs: {"ETag": '"target"'} if kwargs["Body"].read() == original else {}

    path = tmp_path / "input.txt"
    assert files.get_file_size(source) == len(original)
    assert files.download_file(source, str(path), "files")[0]
    assert path.read_bytes() == original
    assert files.upload_file(str(path), target) == (True, f"/files/{target}")

    provider.head_object.assert_called_once_with(Bucket="files", Key=source)
    provider.get_object.assert_called_once_with(Bucket="files", Key=source)
    assert provider.put_object.call_args.kwargs["Key"] == target
    assert provider.put_object.call_args.kwargs["ContentLength"] == len(original)
    assert body.closed
    assert provider.close.call_count == 3


def test_tool_rejects_out_of_scope_bucket_user_and_output_run(storage, tmp_path):
    files, _, factory = storage
    for key, bucket in [("attachments/other/private.txt", None), ("knowledge_base/document.txt", "foreign")]:
        with pytest.raises(ScopeDenied):
            files.get_file_size(key, bucket)
    for key in ("workspace/reader/run-b/outputs/out", "workspace/reader/run-a/outputs/../out"):
        assert not files.upload_file(str(tmp_path / "unused"), key)[0]
    factory.assert_not_called()


def test_failed_transfer_preserves_local_file_and_does_not_retry(storage, tmp_path, monkeypatch):
    files, provider, _ = storage
    path = tmp_path / "input.txt"
    path.write_bytes(b"previous")
    body = BytesIO(b"object grew")
    provider.get_object.return_value = {"Body": body}
    monkeypatch.setattr(run_files, "_MAX_FILE_BYTES", 9)
    assert not files.download_file("knowledge_base/input.txt", str(path))[0]
    assert path.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [path]
    assert body.closed

    provider.put_object.side_effect = ReadTimeoutError(endpoint_url="http://provider.invalid")
    success, message = files.upload_file(str(path), "workspace/reader/run-a/outputs/input.txt")
    assert not success
    assert "outcome is unknown" in message
    assert "provider.invalid" not in message
    assert provider.put_object.call_count == 1
