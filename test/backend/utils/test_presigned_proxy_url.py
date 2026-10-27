# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""The signed object URL cannot choose the file proxy's network authority."""

import pytest
from fastapi import HTTPException

from management.utils.file_http import build_storage_proxy_url


@pytest.mark.parametrize("endpoint", ["https://storage", "https://storage:443/"])
def test_preserves_signed_raw_path_and_query(endpoint):
    url = "https://storage/bucket/a%20b%2Fc.txt?X-Amz-Signature=abc%2Fdef&x=1&x=2"
    target = build_storage_proxy_url(url, endpoint)
    assert target.scheme == "https"
    assert target.host == "storage"
    assert target.raw_path == b"/bucket/a%20b%2Fc.txt?X-Amz-Signature=abc%2Fdef&x=1&x=2"


def test_allows_configured_private_minio():
    target = build_storage_proxy_url("http://minio:9000/bucket/object", "http://minio:9000")
    assert str(target) == "http://minio:9000/bucket/object"


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/", "http://127.0.0.1/file",
    "https://storage.evil.example/file", "https://evil.example/storage/file",
    "http://storage/file", "https://storage:444/file", "https://user@storage/file",
    "https://storage@evil.example/file", "https://storage/file#fragment",
    "//storage/file", "ftp://storage/file", "not a url", "",
    "https://storage:bad/file", "https://storage:99999/file", "https://[broken/file", "https://@storage/file",
    "https://storage\\@evil.example/file", "https://storage/\nfile",
])
def test_rejects_foreign_or_malformed_urls(url):
    with pytest.raises(HTTPException) as raised:
        build_storage_proxy_url(url, "https://storage")
    assert raised.value.status_code == 400


@pytest.mark.parametrize("endpoint", [None, "", "storage:9000", "ftp://storage", "https://user@storage", "https://storage/path", "https://storage?query", "https://storage:bad"])
def test_fails_closed_when_storage_configuration_invalid(endpoint):
    with pytest.raises(HTTPException) as raised:
        build_storage_proxy_url("https://storage/bucket/file", endpoint)
    assert raised.value.status_code == 503


def test_object_path_cannot_replace_configured_authority():
    target = build_storage_proxy_url("https://storage//evil.example/bucket/object", "https://storage")
    assert target.host == "storage"
    assert target.raw_path == b"//evil.example/bucket/object"
