# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""The signed object URL cannot choose the file proxy's network authority."""

import pytest
from fastapi import HTTPException

from management.api.file.http import legacy_storage_object_name


@pytest.mark.parametrize("endpoint", ["https://storage", "https://storage:443/"])
def test_preserves_signed_raw_path_and_query(endpoint):
    url = "https://storage/bucket/a%20b%2Fc.txt?X-Amz-Signature=abc%2Fdef&x=1&x=2"
    assert legacy_storage_object_name(url, endpoint, "bucket") == "a b/c.txt"


def test_configured_private_minio_yields_only_the_key():
    assert legacy_storage_object_name("http://minio:9000/bucket/object", "http://minio:9000", "bucket") == "object"


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
        legacy_storage_object_name(url, "https://storage", "bucket")
    assert raised.value.status_code == 400


@pytest.mark.parametrize("endpoint", [None, "", "storage:9000", "ftp://storage", "https://user@storage", "https://storage/path", "https://storage?query", "https://storage:bad"])
def test_fails_closed_when_storage_configuration_invalid(endpoint):
    with pytest.raises(HTTPException) as raised:
        legacy_storage_object_name("https://storage/bucket/file", endpoint, "bucket")
    assert raised.value.status_code == 503


@pytest.mark.parametrize("path", ["//evil.example/bucket/object", "/foreign/object",
                                  "/bucket/scope/%2e%2e/object", "/bucket/filename%5ctest", "/bucket/"])
def test_invalid_key_or_bucket_is_never_reauthorized(path):
    with pytest.raises(HTTPException) as raised:
        legacy_storage_object_name("https://storage" + path, "https://storage", "bucket")
    assert raised.value.status_code == 400
