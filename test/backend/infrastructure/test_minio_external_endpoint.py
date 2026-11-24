# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""External presign endpoint resolution: scheme inference and opt-out rules.

A bare host:port MINIO_EXTERNAL_ENDPOINT must follow MINIO_SECURE so http-only
deployments do not silently sign https URLs partners cannot use; an explicit
scheme always wins, and unset/empty/internal-equal values keep internal signing.
"""

import pytest

import infrastructure.object_storage.client as client_mod
from infrastructure.object_storage.client import MinioClient


@pytest.fixture()
def external_client(monkeypatch):
    """One MinioClient with a captured boto3 factory and reset lazy cache."""
    captured = {}

    def fake_boto3_client(service, **kwargs):
        captured["service"] = service
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("boto3.client", fake_boto3_client)
    monkeypatch.setattr(client_mod, "MINIO_ENDPOINT", "http://nexent-minio:9000")
    monkeypatch.setattr(client_mod, "MINIO_ACCESS_KEY", "key")
    monkeypatch.setattr(client_mod, "MINIO_SECRET_KEY", "secret")
    instance = MinioClient()
    monkeypatch.setattr(instance, "_external_url_client", None, raising=False)
    return instance, captured


@pytest.mark.parametrize("secure,expected", [(False, "http://192.168.1.10:9010"), (True, "https://192.168.1.10:9010")])
def test_bare_authority_follows_minio_secure(external_client, monkeypatch, secure, expected):
    instance, captured = external_client
    monkeypatch.setattr(client_mod, "MINIO_EXTERNAL_ENDPOINT", "192.168.1.10:9010")
    monkeypatch.setattr(client_mod, "MINIO_SECURE", secure)
    assert instance._get_external_url_client() is not None
    assert captured["endpoint_url"] == expected
    assert captured["config"].signature_version == "s3v4"


def test_explicit_scheme_wins_over_minio_secure(external_client, monkeypatch):
    instance, captured = external_client
    monkeypatch.setattr(client_mod, "MINIO_EXTERNAL_ENDPOINT", "http://files.example.com:9000")
    monkeypatch.setattr(client_mod, "MINIO_SECURE", True)
    assert instance._get_external_url_client() is not None
    assert captured["endpoint_url"] == "http://files.example.com:9000"


@pytest.mark.parametrize("value", ["", "   ", "http://nexent-minio:9000", None, 123])
def test_unset_empty_internal_equal_or_non_string_keeps_internal_signing(external_client, monkeypatch, value):
    instance, captured = external_client
    monkeypatch.setattr(client_mod, "MINIO_EXTERNAL_ENDPOINT", value)
    assert instance._get_external_url_client() is None
    assert captured == {}
