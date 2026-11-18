# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the signed Gateway-to-Ops hop and keep ordinary directories separate."""

import httpx
import pytest
from fastapi import APIRouter

from gateway.application import create_gateway_app
from gateway.configuration import GatewaySettings
from gateway.security.context import trusted_identity
from gateway.security.identity import IDENTITY_HEADER, sign_identity
from ops.api import application as ops_application

SECRET = "gateway-ops-boundary-test-key"
ACTOR = {"kind": "session", "user_id": "user-1", "tenant_id": "tenant-1", "roles": ["USER"]}


@pytest.mark.asyncio
async def test_ops_verifies_the_forwarded_identity_and_keeps_directory_routing(monkeypatch):
    monkeypatch.setattr("gateway.downstream.middleware.enabled", lambda: True)
    monkeypatch.setattr("gateway.downstream.middleware.signing_key", lambda: SECRET)
    monkeypatch.setattr("gateway.downstream.identity.signing_key", lambda: SECRET)
    monkeypatch.setattr(ops_application, "trajectory_enabled", lambda: False)
    # Exercise forwarding and authentication without running configuration business logic.
    monkeypatch.setattr(ops_application, "system_configuration_router", APIRouter())
    ops = ops_application.create_app()

    @ops.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH"])
    async def capture_identity(path: str):
        return {"identity": trusted_identity("session")["user_id"]}

    async def resolve(request, **kwargs):
        return ACTOR

    monkeypatch.setattr("gateway.application.resolve_identity", resolve)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ops), base_url="http://ops") as ops_client:
        async def forward(request):
            if request.url.host == "ops":
                return await ops_client.send(request, stream=True)
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  stream=httpx.ByteStream(b'{"upstream":"management"}'))

        edge = create_gateway_app(
            settings=GatewaySettings(signing_secret=SECRET, ops_url="http://ops", management_url="http://management"),
            transport=httpx.MockTransport(forward), identity_lookup=resolve,
        )
        async with edge.router.lifespan_context(edge):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=edge), base_url="http://edge") as client:
                for method, path in (
                    ("GET", "/api/system_configurations"),
                    ("PATCH", "/api/system_configurations"),
                    ("POST", "/api/system_configurations/recommendations"),
                    ("GET", "/api/trajectory/records"),
                    ("POST", "/api/trajectory/cleanup"),
                    ("PUT", "/api/trajectory/cleanup/schedule"),
                    ("GET", "/api/conversation/agent_groups?view=trajectory"),
                    ("GET", "/api/conversation/agent_groups/agent:42/conversations?view=trajectory"),
                ):
                    response = await client.request(method, path, headers={IDENTITY_HEADER: "untrusted"})
                    assert response.status_code == 200, response.text
                    assert response.json() == {"identity": "user-1"}
                for query in ("", "?view=chat", "?search=trajectory", "?view=trajectory&view=chat", "?view=&view=trajectory"):
                    response = await client.get("/api/conversation/agent_groups" + query)
                    assert response.json() == {"upstream": "management"}
                assert (await client.get("/api/trajectory/unlisted")).status_code == 404
                assert (await client.delete("/api/trajectory/records")).status_code == 404

        path = "/api/trajectory/records"
        assert (await ops_client.get(path)).status_code == 401
        token = sign_identity(ACTOR, "management", "GET", path, b"", key=SECRET)
        assert (await ops_client.get(path, headers={IDENTITY_HEADER: token})).status_code == 401
        token = sign_identity(ACTOR, "ops", "GET", path, b"view=trajectory", key=SECRET)
        assert (await ops_client.get(path, headers={IDENTITY_HEADER: token})).status_code == 401
        assert (await ops_client.get("/health/live")).status_code == 200
