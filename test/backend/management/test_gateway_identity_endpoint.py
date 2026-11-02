# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private lookup rejects invalid signatures/payloads before managed DB work."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from contracts.constants import environment
from infrastructure.service_identity.gateway import sign_lookup
from management.api.identity import gateway_identity as routes


@pytest.fixture
def lookup_app(monkeypatch):
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", "local-lookup-fixture-not-a-deployment-secret")
    run = AsyncMock(return_value={"user_id": "u1", "tenant_id": "t1", "kind": "session"})
    monkeypatch.setattr(routes, "config_thread_manager", SimpleNamespace(run=run))
    app = FastAPI()
    app.include_router(routes.router)
    return app, run


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,status", [("unsigned", 401), ("tampered", 401), ("invalid-json", 400), ("list", 400), ("oversize", 413)])
async def test_invalid_lookup_never_submits_database_work(lookup_app, mode, status):
    app, run = lookup_app
    body = b"{}"
    if mode == "invalid-json": body = b"{"
    if mode == "list": body = b"[]"
    if mode == "oversize": body = b"x" * (16 * 1024 + 1)
    headers = {} if mode == "unsigned" else {"x-nexent-service-token": sign_lookup(b"different" if mode == "tampered" else body)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        response = await client.post("/internal/identity/resolve", content=body, headers=headers)
    assert response.status_code == status
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_lookup_dispatches_to_management_control_lane(lookup_app):
    app, run = lookup_app
    query = {"kind": "session", "user_id": "u1", "token_version": 3}
    body = json.dumps(query).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        response = await client.post("/internal/identity/resolve", content=body,
                                     headers={"x-nexent-service-token": sign_lookup(body)})
    assert response.status_code == 200
    lane, spec, function, submitted = run.await_args.args
    assert lane == "control-io" and spec.task_name == "gateway-identity-lookup"
    assert function is routes.resolve_gateway_identity and submitted == query


@pytest.mark.asyncio
async def test_persistence_failure_does_not_reflect_credential_parameters(lookup_app):
    app, run = lookup_app
    run.side_effect = RuntimeError("SQL parameters: credential=raw-secret-fixture")
    body = b'{"kind":"api_key","access_key":"raw-secret-fixture"}'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        response = await client.post("/internal/identity/resolve", content=body,
                                     headers={"x-nexent-service-token": sign_lookup(body)})
    assert response.status_code == 503
    assert "raw-secret-fixture" not in response.text
