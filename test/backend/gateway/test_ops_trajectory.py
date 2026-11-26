# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the signed Gateway-to-Ops hop and keep ordinary directories separate."""

import httpx
import pytest

from gateway.application import create_gateway_app
from gateway.configuration import GatewaySettings
from gateway.identity.context import trusted_identity
from gateway.identity.protocol import IDENTITY_HEADER, sign_identity
from ops.api import application as ops_application
from ops.api import system_configurations

SECRET = "gateway-ops-boundary-test-key"
ACTOR = {"kind": "session", "user_id": "user-1", "tenant_id": "tenant-1", "roles": ["USER"]}


@pytest.mark.asyncio
async def test_ops_verifies_the_forwarded_identity_and_keeps_directory_routing(monkeypatch):
    monkeypatch.setattr("gateway.identity.middleware.enabled", lambda: True)
    monkeypatch.setattr("gateway.identity.middleware.signing_key", lambda: SECRET)
    monkeypatch.setattr("gateway.identity.downstream.signing_key", lambda: SECRET)
    monkeypatch.setattr(ops_application, "trajectory_enabled", lambda: False)
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


@pytest.mark.asyncio
async def test_gateway_reaches_real_system_configuration_routes(monkeypatch, mocker):
    monkeypatch.setattr("gateway.identity.middleware.enabled", lambda: True)
    monkeypatch.setattr("gateway.identity.middleware.signing_key", lambda: SECRET)
    monkeypatch.setattr("gateway.identity.downstream.signing_key", lambda: SECRET)
    monkeypatch.setattr(ops_application, "trajectory_enabled", lambda: False)

    async def resolve(request, **kwargs):
        return {**ACTOR, "roles": ["SU"]}

    monkeypatch.setattr("gateway.application.resolve_identity", resolve)
    monkeypatch.setattr(
        "permissions.operations.has_permission",
        lambda roles, permission: "SU" in roles and permission.startswith("ops.configuration:"),
    )

    async def inline(_manager, function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(system_configurations, "run_system_configuration_io", inline)
    load = mocker.patch.object(system_configurations, "list_system_configurations", return_value=[])
    save = mocker.patch.object(system_configurations, "save_system_configurations", return_value={"changed": 1})
    ops = ops_application.create_app()
    ops.state.thread_manager = object()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ops), base_url="http://ops") as ops_client:
        async def forward(request):
            assert request.url.host == "ops"
            return await ops_client.send(request, stream=True)

        edge = create_gateway_app(
            settings=GatewaySettings(signing_secret=SECRET, ops_url="http://ops"),
            transport=httpx.MockTransport(forward), identity_lookup=resolve,
        )
        async with edge.router.lifespan_context(edge):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=edge), base_url="http://edge") as client:
                path = "/api/system_configurations"
                result = await client.get(path)
                assert result.status_code == 200, result.text
                assert result.json() == {"items": [], "total": 0}
                changes = {"MAX_TENANT_COUNT": 5}
                result = await client.patch(path, json={"changes": changes})
                assert result.status_code == 200, result.text
                assert result.json() == {"saved": True, "changed": 1}
                result = await client.post(f"{path}/recommendations", json={"key": "MAX_TENANT_COUNT"})
                assert result.status_code == 400, result.text
                assert result.json()["detail"]["code"] == "RECOMMENDATION_UNAVAILABLE"
                load.assert_called_once_with()
                save.assert_called_once_with(changes, actor=ACTOR["user_id"])
