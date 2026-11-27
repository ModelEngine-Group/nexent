# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""The signed object URL cannot choose the file proxy's network authority."""

import pytest
from fastapi import HTTPException

from management.api.file.http import build_storage_proxy_url


SIGNED_QUERY = (
    "X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=fixture%2F20261127%2Fus-east-1%2Fs3%2Faws4_request"
    "&X-Amz-Date=20261127T000000Z&X-Amz-Expires=300&X-Amz-SignedHeaders=host&X-Amz-Signature=abc%2Fdef"
)


@pytest.mark.parametrize("endpoint", ["https://storage", "https://storage:443/"])
def test_preserves_signed_raw_path_and_query(endpoint):
    url = f"https://storage/bucket/a%20b%2Fc.txt?{SIGNED_QUERY}&x=1&x=2"
    target = build_storage_proxy_url(url, endpoint)
    assert target.scheme == "https"
    assert target.host == "storage"
    assert target.raw_path == f"/bucket/a%20b%2Fc.txt?{SIGNED_QUERY}&x=1&x=2".encode("ascii")


def test_allows_configured_private_minio():
    target = build_storage_proxy_url(f"http://minio:9000/bucket/object?{SIGNED_QUERY}", "http://minio:9000")
    assert str(target) == f"http://minio:9000/bucket/object?{SIGNED_QUERY}"


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
    target = build_storage_proxy_url(f"https://storage//evil.example/bucket/object?{SIGNED_QUERY}", "https://storage")
    assert target.host == "storage"
    assert target.raw_path == f"//evil.example/bucket/object?{SIGNED_QUERY}".encode("ascii")


def test_external_authority_url_is_rejected_for_internal_proxy():
    """P1 regression: a partner-facing external presigned URL must never be
    fed to the internal proxy — the same-origin guard rejects it with 400.
    Internal flows therefore must keep signing against MINIO_ENDPOINT."""
    with pytest.raises(HTTPException) as raised:
        build_storage_proxy_url(
            "https://files.example.com/bucket/object?X-Amz-Signature=abc",
            "http://minio:9000",
        )
    assert raised.value.status_code == 400


@pytest.mark.parametrize("query", [
    "",
    "X-Amz-Signature=placeholder",
    SIGNED_QUERY.replace("AWS4-HMAC-SHA256", "unknown"),
    SIGNED_QUERY.replace("X-Amz-Credential=", "ignored="),
    SIGNED_QUERY.replace("X-Amz-Signature=abc%2Fdef", "X-Amz-Signature="),
    SIGNED_QUERY + "&X-Amz-Signature=second",
])
def test_rejects_missing_or_ambiguous_presigned_credentials(query):
    with pytest.raises(HTTPException, match="presigned URL") as raised:
        build_storage_proxy_url(f"https://storage/bucket/object?{query}", "https://storage")
    assert raised.value.status_code == 400
