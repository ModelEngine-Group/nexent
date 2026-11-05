# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Northbound API-key download contract for one AIDP original file."""

from contextlib import contextmanager
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from ext_components.aidp.consts.aidp_exceptions import (
    AidpKbNotFoundError,
    AidpKbPermissionDeniedError,
)
from gateway.api import northbound
from gateway.authentication import northbound_auth

CASE_ID = "AIDP-FILE-IDENTITY-D2-001"
KDS_ID = "kb-42"
FILE_UUID = "11111111-2222-4333-8444-555555555555"
DOWNLOAD_PATH = f"/nb/v1/knowledge-bases/{KDS_ID}/files/{FILE_UUID}/download"
AIDP_INTERNAL_URL = "https://aidp.internal"
AIDP_SECRET = "aidp-secret"
NORTHBOUND_KEY = "good-key"

pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D2")]


class FakeAidpResponse:
    def __init__(self, closed: list[bool]):
        self.headers = {
            "Content-Type": "application/pdf",
            "Content-Disposition": 'attachment; filename="manual.pdf"',
            "X-File-Size": "14",
        }
        self._closed = closed

    async def aiter_bytes(self):
        for part in (b"original-", b"bytes"):
            yield part

    async def aclose(self):
        self._closed.append(True)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(northbound.router)
    with TestClient(app) as test_client:
        yield test_client


def _authorize(authorization):
    valid = authorization == f"Bearer {NORTHBOUND_KEY}"
    return valid, {"user_id": "user-1", "token_id": 1} if valid else None


@contextmanager
def configured(
    *,
    permission_error=None,
    upstream=None,
    permission_calls=None,
    upstream_calls=None,
):
    def require_permission(kds_id, user_id, tenant_id, required):
        if permission_calls is not None:
            permission_calls.append((kds_id, user_id, tenant_id, required))
        if permission_error is not None:
            raise permission_error
        return SimpleNamespace(permission="READ_ONLY")

    async def default_upstream(server_url, api_key, kds_id, file_uuid):
        if upstream_calls is not None:
            upstream_calls.append((server_url, api_key, kds_id, file_uuid))
        return FakeAidpResponse([])

    with patch.object(
        northbound_auth, "validate_bearer_token", side_effect=_authorize
    ), patch.object(
        northbound_auth,
        "get_user_and_tenant_by_access_key",
        return_value={
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "token_id": 1,
        },
    ), patch.object(
        northbound_auth, "log_token_usage"
    ), patch.object(
        northbound, "AIDP_SERVER_URL", AIDP_INTERNAL_URL
    ), patch.object(
        northbound, "AIDP_API_KEY", AIDP_SECRET
    ), patch.object(
        northbound, "require_permission", side_effect=require_permission
    ), patch.object(
        northbound,
        "stream_aidp_doc_impl",
        new=upstream or default_upstream,
    ):
        yield


def test_authorized_download_streams_original_bytes_and_metadata(client):
    permission_calls = []
    upstream_calls = []
    closed: list[bool] = []

    async def upstream(server_url, api_key, kds_id, file_uuid):
        upstream_calls.append((server_url, api_key, kds_id, file_uuid))
        return FakeAidpResponse(closed)

    with configured(
        permission_calls=permission_calls,
        upstream_calls=upstream_calls,
        upstream=upstream,
    ):
        response = client.get(
            DOWNLOAD_PATH, headers={"Authorization": f"Bearer {NORTHBOUND_KEY}"}
        )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"original-bytes"
    assert response.headers["content-type"].startswith("application/pdf")
    assert "manual.pdf" in response.headers["content-disposition"]
    assert response.headers["x-file-size"] == "14"
    assert permission_calls == [(KDS_ID, "user-1", "tenant-1", "READ")]
    assert upstream_calls == [
        (AIDP_INTERNAL_URL, AIDP_SECRET, KDS_ID, FILE_UUID)
    ]
    assert AIDP_SECRET not in str(dict(response.headers))
    assert AIDP_INTERNAL_URL not in str(dict(response.headers))
    assert closed == [True]


@pytest.mark.parametrize(
    "authorization,reason",
    [(None, "missing"), ("Bearer wrong-key", "wrong")],
)
def test_missing_or_invalid_key_is_rejected_before_permission(
    client, authorization, reason
):
    permission_calls = []
    upstream_calls = []
    headers = {} if authorization is None else {"Authorization": authorization}

    with configured(
        permission_calls=permission_calls,
        upstream_calls=upstream_calls,
    ):
        response = client.get(DOWNLOAD_PATH, headers=headers)

    assert response.status_code == HTTPStatus.UNAUTHORIZED, reason
    assert permission_calls == []
    assert upstream_calls == []


@pytest.mark.parametrize(
    "error,expected_status",
    [
        (
            AidpKbPermissionDeniedError(
                kb_id=KDS_ID, user_id="user-1", required="READ"
            ),
            HTTPStatus.FORBIDDEN,
        ),
        (
            AidpKbNotFoundError(kb_id=KDS_ID, tenant_id="tenant-1"),
            HTTPStatus.NOT_FOUND,
        ),
    ],
)
def test_permission_failure_never_reaches_aidp(
    client, error, expected_status
):
    upstream_calls = []

    with configured(permission_error=error, upstream_calls=upstream_calls):
        response = client.get(
            DOWNLOAD_PATH, headers={"Authorization": f"Bearer {NORTHBOUND_KEY}"}
        )

    assert response.status_code == expected_status
    assert upstream_calls == []
    assert KDS_ID not in response.text


def test_invalid_file_uuid_is_rejected_before_permission(client):
    permission_calls = []
    upstream_calls = []

    with configured(
        permission_calls=permission_calls,
        upstream_calls=upstream_calls,
    ):
        response = client.get(
            "/nb/v1/knowledge-bases/kb-42/files/not-a-uuid/download",
            headers={"Authorization": f"Bearer {NORTHBOUND_KEY}"},
        )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert permission_calls == []
    assert upstream_calls == []


def test_aidp_file_not_found_maps_to_404(client):
    async def upstream(*_args, **_kwargs):
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            "upstream detail must not leak",
            details={"upstream_status": 404},
        )

    with configured(upstream=upstream):
        response = client.get(
            DOWNLOAD_PATH, headers={"Authorization": f"Bearer {NORTHBOUND_KEY}"}
        )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert "upstream detail" not in response.text


@pytest.mark.parametrize(
    "error",
    [
        AppException(ErrorCode.AIDP_AUTH_ERROR, "AIDP authentication detail"),
        RuntimeError("unexpected upstream failure"),
    ],
)
def test_upstream_failures_do_not_leak_credentials_or_details(client, error):
    async def upstream(*_args, **_kwargs):
        raise error

    with configured(upstream=upstream):
        response = client.get(
            DOWNLOAD_PATH, headers={"Authorization": f"Bearer {NORTHBOUND_KEY}"}
        )

    assert response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
    assert AIDP_SECRET not in response.text
    assert "AIDP authentication detail" not in response.text
    assert "unexpected upstream failure" not in response.text
