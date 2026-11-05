# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Concurrency and security isolation for the northbound AIDP file download."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from ext_components.aidp.consts.aidp_exceptions import AidpKbPermissionDeniedError
from gateway.api import northbound
from gateway.authentication import northbound_auth
from nexent.core.ext_components.aidp.aidp_search_tool import AidpSearchTool

CASE_ID = "AIDP-FILE-IDENTITY-D5-001"
ALLOWED_KB = "kb-allowed"
OTHER_KB = "kb-other"
FILE_ONE = "11111111-2222-4333-8444-555555555555"
FILE_TWO = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
API_KEY_ONE = "user-1-key"
API_KEY_TWO = "user-2-key"
NORTHBOUND_BASE = "https://api.example.com/api"

pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D5")]

_USER_BY_KEY = {
    API_KEY_ONE: ("user-1", "tenant-1"),
    API_KEY_TWO: ("user-2", "tenant-1"),
}
_READABLE = {
    "user-1": {ALLOWED_KB},
    "user-2": {OTHER_KB},
}


def _authorize(authorization):
    token = (authorization or "").removeprefix("Bearer ").strip()
    valid = token in _USER_BY_KEY
    return (
        valid,
        {"user_id": _USER_BY_KEY[token][0], "token_id": 1} if valid else None,
    )


def _resolve_identity(access_key):
    user_id, tenant_id = _USER_BY_KEY[access_key]
    return {"user_id": user_id, "tenant_id": tenant_id, "token_id": 1}


class FakeAidpResponse:
    def __init__(self, payload: bytes):
        self.headers = {
            "Content-Type": "text/plain",
            "Content-Disposition": 'attachment; filename="original.txt"',
            "X-File-Size": str(len(payload)),
        }
        self._payload = payload

    async def aiter_bytes(self):
        yield self._payload

    async def aclose(self):
        return None


def _app():
    app = FastAPI()
    app.include_router(northbound.router)
    return app


@contextmanager
def configured(*, upstream=None, permission_calls=None, upstream_calls=None):
    def require_permission(kds_id, user_id, tenant_id, required):
        if permission_calls is not None:
            permission_calls.append((kds_id, user_id, tenant_id, required))
        if kds_id not in _READABLE.get(user_id, set()):
            raise AidpKbPermissionDeniedError(
                kb_id=kds_id, user_id=user_id, required=required
            )
        return SimpleNamespace(permission="READ_ONLY")

    async def default_upstream(server_url, api_key, kds_id, file_uuid):
        if upstream_calls is not None:
            upstream_calls.append((kds_id, file_uuid))
        await asyncio.sleep(0.02)
        return FakeAidpResponse(f"{kds_id}:{file_uuid}".encode())

    with patch.object(
        northbound_auth, "validate_bearer_token", side_effect=_authorize
    ), patch.object(
        northbound_auth,
        "get_user_and_tenant_by_access_key",
        side_effect=_resolve_identity,
    ), patch.object(
        northbound_auth, "log_token_usage"
    ), patch.object(
        northbound, "AIDP_SERVER_URL", "https://aidp.internal"
    ), patch.object(
        northbound, "AIDP_API_KEY", "aidp-secret"
    ), patch.object(
        northbound, "require_permission", side_effect=require_permission
    ), patch.object(
        northbound,
        "stream_aidp_doc_impl",
        new=upstream or default_upstream,
    ):
        yield


async def _fetch(client, kds_id, file_uuid, key):
    headers = {} if key is None else {"Authorization": f"Bearer {key}"}
    return await client.get(
        f"/nb/v1/knowledge-bases/{kds_id}/files/{file_uuid}/download",
        headers=headers,
    )


@pytest.mark.asyncio
async def test_concurrent_downloads_stay_isolated_per_request():
    upstream_calls = []
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://northbound.test"
    ) as client:
        with configured(upstream_calls=upstream_calls):
            first, second = await asyncio.gather(
                _fetch(client, ALLOWED_KB, FILE_ONE, API_KEY_ONE),
                _fetch(client, OTHER_KB, FILE_TWO, API_KEY_TWO),
            )

    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.OK
    assert first.content == f"{ALLOWED_KB}:{FILE_ONE}".encode()
    assert second.content == f"{OTHER_KB}:{FILE_TWO}".encode()
    assert sorted(upstream_calls) == sorted(
        [(ALLOWED_KB, FILE_ONE), (OTHER_KB, FILE_TWO)]
    )
    for response in (first, second):
        assert API_KEY_ONE not in response.text
        assert API_KEY_TWO not in response.text
        assert "aidp-secret" not in str(dict(response.headers))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kds_id,key,expected_status",
    [
        (OTHER_KB, API_KEY_ONE, HTTPStatus.FORBIDDEN),
        (ALLOWED_KB, None, HTTPStatus.UNAUTHORIZED),
        (ALLOWED_KB, "wrong-key", HTTPStatus.UNAUTHORIZED),
    ],
)
async def test_unauthorized_or_unauthenticated_never_reaches_aidp(
    kds_id, key, expected_status
):
    upstream_calls = []
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://northbound.test"
    ) as client:
        with configured(upstream_calls=upstream_calls):
            response = await _fetch(client, kds_id, FILE_ONE, key)

    assert response.status_code == expected_status
    assert upstream_calls == []
    assert "aidp-secret" not in response.text
    assert API_KEY_ONE not in response.text


@pytest.mark.asyncio
async def test_cross_knowledge_base_file_is_rejected_by_aidp_scope():
    upstream_calls = []

    async def missing_file(server_url, api_key, kds_id, file_uuid):
        upstream_calls.append((kds_id, file_uuid))
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            "AIDP file detail",
            details={"upstream_status": 404},
        )

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://northbound.test"
    ) as client:
        with configured(upstream=missing_file, upstream_calls=upstream_calls):
            response = await _fetch(client, ALLOWED_KB, FILE_TWO, API_KEY_ONE)

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert upstream_calls == [(ALLOWED_KB, FILE_TWO)]
    assert "AIDP file detail" not in response.text


def _chunk(title: str, kds_id: str, file_uuid: str):
    return {
        "id": f"chunk-{title}",
        "chunk_type": "text",
        "title": title,
        "text": "fixture chunk",
        "file_url": "",
        "metadata": {"kds_id": kds_id, "file_uuid": file_uuid},
    }


def test_northbound_and_page_tool_instances_do_not_share_the_link():
    def build():
        return AidpSearchTool(
            server_url="https://aidp.test",
            api_key="aidp-secret",
            tenant_id="aidp",
            kds_list='["kb-allowed"]',
            top_k=1,
        )

    northbound_tool = build()
    page_tool = build()
    northbound_tool.set_northbound_download(NORTHBOUND_BASE)

    def process(tool):
        return tool._process_records([_chunk("Manual.pdf", ALLOWED_KB, FILE_ONE)])[1][0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        northbound_result, page_result = list(
            pool.map(process, [northbound_tool, page_tool])
        )

    expected = (
        f"{NORTHBOUND_BASE}/nb/v1/knowledge-bases/{ALLOWED_KB}/files/"
        f"{FILE_ONE}/download"
    )
    assert northbound_result["northbound_api_download_url"] == expected
    assert "northbound_api_download_url" not in page_result
    assert "aidp-secret" not in str(northbound_result)
