# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-FILE-HTTP-01: body-bound reverse calls and bounded single attempts."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from contracts.agentos import ManagementOperation
from contracts.agentos_knowledge import (
    FileCleanseLookup,
    FileCleanseState,
    KnowledgeOperation,
)
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from fastapi import FastAPI
from management.api.file import agentos_cleanse
from nexent.storage.errors import ScopeDenied

from infrastructure.agentos_client import AgentOSClient
from infrastructure.agentos_identity import ServicePrincipal, sign_call
from test.backend.services.test_run_cleanse_service import request


@pytest.fixture
def endpoint(mocker):
    mocker.patch.object(environment, "JWT_SECRET", "synthetic-cleanse-signature")
    state = FileCleanseState(run_id="a" * 32, job_id="c" * 32, status="queued")
    service = MagicMock()
    service.submit.return_value = service.inspect.return_value = state
    service.cancel.return_value = state.model_copy(update={"status": "cancelled"})
    service.statuses = []

    async def observe_status(response):
        service.statuses.append(response.status_code)

    async def controlled_worker(name, action, *args, **kwargs):
        return action(*args, **{key: value for key, value in kwargs.items() if key not in {"lane", "owner"}})

    mocker.patch.object(agentos_cleanse, "run_blocking", side_effect=controlled_worker)
    app = FastAPI()
    app.include_router(agentos_cleanse.create_file_cleanse_router(service), prefix="/api")
    transport = httpx.ASGITransport(app=app)
    client = AgentOSClient("http://management", lambda **kwargs: httpx.AsyncClient(
        transport=transport, event_hooks={"response": [observe_status]}, **kwargs,
    ))
    return client, service, state


async def test_client_uses_signed_submit_inspect_cancel(endpoint):
    client, service, state = endpoint
    assert await client.submit_file_cleanse(request(), "user-a", "tenant-a") == state
    lookup = FileCleanseLookup(run_id=state.run_id, job_id=state.job_id)
    assert await client.inspect_file_cleanse(lookup, "user-a", "tenant-a") == state
    assert (await client.cancel_file_cleanse(lookup, "user-a", "tenant-a")).status == "cancelled"
    assert service.statuses == [202, 200, 200]
    for action in (service.submit, service.inspect, service.cancel):
        action.assert_called_once()
        assert action.call_args.kwargs["user_id"] == "user-a"
        assert action.call_args.kwargs["tenant_id"] == "tenant-a"
        assert 0 < action.call_args.kwargs["context"].remaining() <= 10


@pytest.mark.parametrize("changed,expected", [("body", 401), ("audience", 401), ("operation", 401), ("query", 400), ("large", 413)])
async def test_invalid_signed_request_has_no_job_side_effect(endpoint, changed, expected):
    client, service, _ = endpoint
    operation = ManagementOperation.FILE_CLEANSE
    body = request().model_dump_json().encode()
    signed_operation = KnowledgeOperation.UPLOAD if changed == "audience" else (
        ManagementOperation.FILE_CLEANSE_STATUS if changed == "operation" else operation
    )
    token = sign_call(signed_operation,
                      body, ServicePrincipal("user-a", "tenant-a"))
    body = body + b" " if changed == "body" else b"x" * 17000 if changed == "large" else body
    async with client.create_client() as http:
        response = await http.post("http://management/api" + operation.value + ("?x=1" if changed == "query" else ""),
                                   content=body, headers={"Authorization": "Bearer " + token})
    assert response.status_code == expected
    service.submit.assert_not_called()


async def test_denied_scope_maps_to_file_error_without_private_details(endpoint):
    client, service, _ = endpoint
    service.submit.side_effect = ScopeDenied()
    async with client.create_client() as http:
        body = request().model_dump_json().encode()
        token = sign_call(ManagementOperation.FILE_CLEANSE, body, ServicePrincipal("user-a", "tenant-a"))
        response = await http.post("http://management/api" + ManagementOperation.FILE_CLEANSE.value,
                                   content=body, headers={"Authorization": "Bearer " + token})
    assert response.status_code == 403 and response.json() == {"code": "FILE_CLEANSE_FORBIDDEN"}


async def test_total_client_deadline_cancels_one_request_and_closes_once(mocker, caplog):
    mocker.patch.object(environment, "JWT_SECRET", "synthetic-cleanse-signature")
    mocker.patch("infrastructure.agentos_client._KNOWLEDGE_DEADLINE_SECONDS", 0.01)
    cancelled = []

    async def stalled(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    http = MagicMock()
    http.post = AsyncMock(side_effect=stalled)
    http.aclose = AsyncMock()
    http.__aenter__ = AsyncMock(return_value=http)

    async def close(*args):
        await http.aclose()
        return False

    http.__aexit__ = AsyncMock(side_effect=close)
    factory = MagicMock(return_value=http)
    client = AgentOSClient("http://private.invalid", factory)
    with pytest.raises(RuntimeServiceTimeoutError):
        await client.submit_file_cleanse(request(), "user-a", "tenant-a")
    assert cancelled == [True]
    http.post.assert_awaited_once()
    http.aclose.assert_awaited_once()
    factory.assert_called_once()
    assert "agentos_file_cleanse_timeout" in caplog.text
    assert "private.invalid" not in caplog.text
    assert not any(row.levelname == "ERROR" for row in caplog.records)


async def test_receiver_deadline_cancels_record_action_once(endpoint, mocker, caplog):
    client, service, _ = endpoint
    mocker.patch.object(agentos_cleanse, "_DEADLINE_SECONDS", 0.01)
    cancelled = []

    async def stalled(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    work = mocker.patch.object(agentos_cleanse, "run_blocking", side_effect=stalled)
    with pytest.raises(RuntimeUpstreamError) as captured:
        await client.submit_file_cleanse(request(), "user-a", "tenant-a")
    assert captured.value.status_code == 504
    assert captured.value.content == b'{"code":"FILE_CLEANSE_TIMEOUT"}'
    assert cancelled == [True]
    work.assert_awaited_once()
    service.submit.assert_not_called()
    assert "file_cleanse_timeout" in caplog.text
    assert not any(row.levelname == "ERROR" for row in caplog.records)
