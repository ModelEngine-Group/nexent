# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Model monitoring uses the signed Gateway session and Ops role boundary."""

from types import SimpleNamespace

import httpx
import pytest

from gateway.application import create_gateway_app
from gateway.configuration import GatewaySettings
from gateway.exposure.registry import default_registry
from ops.api import application as ops_application
from ops.api import monitoring
from permissions import rbac


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["models", "agents"])
async def test_monitoring_requires_an_ops_session_and_a_signed_gateway_hop(monkeypatch, resource):
    secret = "isolated-ops-model-gateway-signature"
    actor = {"kind": "session", "user_id": "operator", "tenant_id": "tenant", "roles": ["OPS"]}
    monkeypatch.setattr("gateway.identity.middleware.enabled", lambda: True)
    monkeypatch.setattr("gateway.identity.middleware.signing_key", lambda: secret)
    monkeypatch.setattr("gateway.identity.downstream.signing_key", lambda: secret)
    monkeypatch.setattr(ops_application, "OPS_MONITORING_ENABLED", True)
    monkeypatch.setattr(ops_application, "trajectory_enabled", lambda: False)
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read", "ops.dashboard:update"}})
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    monkeypatch.setattr(monitoring, "read_models", lambda *args, **kwargs: (
        [], [], [], {"data_as_of": None, "coverage_state": "uncovered", "is_stale": False},
    ))
    status = {"data_as_of": None, "coverage_state": "uncovered", "is_stale": False}
    monkeypatch.setattr(monitoring, "read_agents", lambda *args, **kwargs: ({}, status))
    monkeypatch.setattr(monitoring, "read_agent_tokens", lambda *args, **kwargs: SimpleNamespace(tokens={}, status=status))
    ops = ops_application.create_app()
    ops.state.monitoring = SimpleNamespace()

    async def resolve(*args, **kwargs):
        return actor

    monkeypatch.setattr("gateway.application.resolve_identity", resolve)
    path = f"/api/ops/v1/monitoring/{resource}/summary"
    params = {"start_date": "2026-11-18", "end_date": "2026-11-19"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ops), base_url="http://ops") as downstream:
        async def forward(request):
            assert request.url.host == "ops"
            response = await downstream.send(request)
            return httpx.Response(response.status_code, headers=response.headers,
                                  stream=httpx.ByteStream(response.content))

        edge = create_gateway_app(settings=GatewaySettings(signing_secret=secret, ops_url="http://ops"),
                                  transport=httpx.MockTransport(forward), identity_lookup=resolve)
        async with edge.router.lifespan_context(edge):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=edge), base_url="http://gateway") as client:
                assert (await client.get(path, params=params)).status_code == 200
                assert (await client.get(path, params={**params, "tenant_id": "other"})).status_code == 403
                actor["roles"] = ["USER"]
                assert (await client.get(path, params=params)).status_code == 403
                actor["kind"] = "api_key"
                assert (await client.get(path, params=params)).status_code == 401
                assert (await client.get("/api/ops/v1/monitoring/unlisted")).status_code == 404
        assert (await downstream.get(path, params=params)).status_code == 401


@pytest.mark.parametrize("method,resource,suffix", [
    ("GET", resource, suffix) for resource in ("models", "agents")
    for suffix in ("", "/summary", "/trends", "/rankings")
] + [
    ("POST", "models", "/refresh"), ("GET", "models", "/refreshes/example"),
])
def test_monitoring_exposure_is_limited_to_declared_ops_session_routes(method, resource, suffix):
    match = default_registry().match(method, f"/api/ops/v1/monitoring/{resource}" + suffix)
    assert match.target == "ops"
    assert match.credential_kinds == ("session",)
