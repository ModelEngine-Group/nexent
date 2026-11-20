# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ReadTimeoutError
from nexent.multi_modal.load_save_object import LoadSaveObjectManager

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.object_storage import analysis_files


@pytest.fixture
def provider(monkeypatch):
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(analysis_files, "_configured_client", factory)
    monkeypatch.setattr(
        analysis_files, "_configured_environment",
        lambda: SimpleNamespace(MINIO_DEFAULT_BUCKET="files"),
    )
    return client, factory


@pytest.mark.parametrize("role", ["management", "runtime"])
def test_analysis_uses_one_exact_get_and_releases_provider_before_return(provider, role):
    client, _ = provider
    body = BytesIO(b"analysis input")
    client.get_object.return_value = {"Body": body}
    adapter = analysis_files.AnalysisFileStorage(ServicePrincipal("reader", "tenant-a"), role=role)
    manager = LoadSaveObjectManager(storage_client=adapter)

    result = manager.download_file_from_url("s3:/files/attachments/reader/input.txt", url_type="s3")

    assert result == b"analysis input"
    client.get_object.assert_called_once_with(Bucket="files", Key="attachments/reader/input.txt")
    client.head_object.assert_not_called()
    client.close.assert_called_once()
    assert body.closed


@pytest.mark.parametrize(("url", "role"), [
    ("s3://files/attachments/other/input.txt", "runtime"),
    ("/foreign/knowledge_base/input.txt", "management"),
    ("//files/attachments/other/input.txt", "management"),
    ("s3://files/knowledge_base/input.txt", "gateway"),
])
def test_analysis_denies_cross_scope_reads_without_a_provider_call(provider, url, role):
    _, factory = provider
    adapter = analysis_files.AnalysisFileStorage(ServicePrincipal("reader", "tenant-a"), role=role)

    assert LoadSaveObjectManager(storage_client=adapter).download_file_from_url(url, url_type="s3") is None
    factory.assert_not_called()


def test_analysis_provider_read_timeout_closes_body_and_does_not_retry(provider):
    client, _ = provider
    body = Mock()
    body.read.side_effect = ReadTimeoutError(endpoint_url="http://provider.invalid")
    client.get_object.return_value = {"Body": body}
    adapter = analysis_files.AnalysisFileStorage(ServicePrincipal("reader", "tenant-a"), role="runtime")

    ok, result = adapter.get_file_stream("knowledge_base/input.txt", "files")

    assert not ok
    assert result == "Storage is unavailable"
    assert client.get_object.call_count == 1
    client.close.assert_called_once()
    body.close.assert_called_once()


def test_analysis_cancellation_during_read_releases_provider(provider):
    client, _ = provider
    cancelled = Event()
    body = Mock()

    def read_chunk(_size):
        cancelled.set()
        return b"partial input"

    body.read.side_effect = read_chunk
    client.get_object.return_value = {"Body": body}
    adapter = analysis_files.AnalysisFileStorage(
        ServicePrincipal("reader", "tenant-a"), role="runtime", cancelled=cancelled,
    )

    assert adapter.get_file_stream("knowledge_base/input.txt", "files") == (False, "Storage operation was cancelled")
    body.read.assert_called_once()
    body.close.assert_called_once()
    client.close.assert_called_once()
