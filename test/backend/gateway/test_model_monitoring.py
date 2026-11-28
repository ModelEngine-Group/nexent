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
@pytest.mark.parametrize("resource", ["models", "agents", "skills"])
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
    monkeypatch.setattr(monitoring, "read_skills", lambda *args, **kwargs: (
        [], [], [], {**status, "coverage_state": "uncovered"},
    ))
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
    ("GET", resource, suffix) for resource in ("models", "agents", "skills")
    for suffix in ("", "/summary", "/trends", "/rankings")
] + [
    ("POST", resource, "/refresh") for resource in ("models", "skills")
] + [
    ("GET", resource, "/refreshes/example") for resource in ("models", "skills")
])
def test_monitoring_exposure_is_limited_to_declared_ops_session_routes(method, resource, suffix):
    match = default_registry().match(method, f"/api/ops/v1/monitoring/{resource}" + suffix)
    assert match.target == "ops"
    assert match.credential_kinds == ("session",)


@pytest.mark.asyncio
async def test_nb_monitoring_reuses_ops_handlers_behind_the_api_key_hop(monkeypatch):
    """The /nb mirror resolves the signed API-key identity and answers enveloped."""
    secret = "isolated-nb-ops-gateway-signature"
    actor = {"kind": "api_key", "user_id": "partner-user", "tenant_id": "tenantA", "roles": []}
    monkeypatch.setattr("gateway.identity.middleware.enabled", lambda: True)
    monkeypatch.setattr("gateway.identity.middleware.signing_key", lambda: secret)
    monkeypatch.setattr("gateway.identity.downstream.signing_key", lambda: secret)
    monkeypatch.setattr(ops_application, "OPS_MONITORING_ENABLED", True)
    monkeypatch.setattr(ops_application, "trajectory_enabled", lambda: False)
    monkeypatch.setattr(monitoring, "read_models", lambda *args, **kwargs: (
        [], [], [], {"data_as_of": None, "coverage_state": "uncovered", "is_stale": False},
    ))
    ops = ops_application.create_app()
    ops.state.monitoring = SimpleNamespace()

    async def resolve(*args, **kwargs):
        return actor

    monkeypatch.setattr("gateway.application.resolve_identity", resolve)
    path = "/nb/v1/monitoring/models/summary"
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
                response = await client.get(path, params=params)
                assert response.status_code == 200
                body = response.json()
                assert set(body) == {"message", "data", "requestId"}
                assert body["message"] == "success"
                assert set(body["data"]) == {"data", "coverage_state", "is_stale", "data_as_of"}
                denied = await client.get(path, params={**params, "tenant_id": "tenantB"})
                assert denied.status_code == 403
                assert denied.json()["code"] == "HTTP_403"
                actor["kind"] = "session"
                assert (await client.get(path, params=params)).status_code == 401
                actor["kind"] = "api_key"
                assert (await client.get("/nb/v1/monitoring/unlisted")).status_code == 404
        assert (await downstream.get(path, params=params)).status_code == 401


@pytest.mark.asyncio
async def test_nb_monitoring_routes_every_declared_route_through_the_signed_hop(monkeypatch):
    """All 24 /nb/ops routes traverse the gateway API-key hop and answer enveloped."""
    from unittest.mock import Mock

    secret = "isolated-nb-ops-gateway-signature"
    actor = {"kind": "api_key", "user_id": "partner-user", "tenant_id": "tenantA", "roles": []}
    day = "2026-11-18"
    coverage = {"data_as_of": None, "coverage_state": "covered", "is_stale": False}
    usage = SimpleNamespace(agents={}, days={}, tokens={}, status=coverage)
    monkeypatch.setattr("gateway.identity.middleware.enabled", lambda: True)
    monkeypatch.setattr("gateway.identity.middleware.signing_key", lambda: secret)
    monkeypatch.setattr("gateway.identity.downstream.signing_key", lambda: secret)
    monkeypatch.setattr(ops_application, "OPS_MONITORING_ENABLED", True)
    monkeypatch.setattr(ops_application, "trajectory_enabled", lambda: False)
    monkeypatch.setattr(monitoring, "JWT_SECRET", "isolated-nb-ops-integration-jwt-secret")
    monkeypatch.setattr(monitoring, "read_models", lambda *a, **k: ([], [], [], coverage))
    monkeypatch.setattr(monitoring, "read_skills", lambda *a, **k: ([], [], [], coverage))
    monkeypatch.setattr(monitoring, "read_agents", lambda *a, **k: ({}, coverage))
    monkeypatch.setattr(monitoring, "read_agent_views", lambda *a, **k: ([], 0, [], coverage))
    monkeypatch.setattr(monitoring, "read_agent_tokens", lambda *a, **k: usage)
    monkeypatch.setattr(monitoring, "read_mcp_tools", lambda *a, **k: ([], [], [], coverage))
    monkeypatch.setattr(monitoring, "mcp_server_catalog", lambda *a, **k: [])
    monkeypatch.setattr(monitoring, "mcp_services_by_tenant", lambda *a, **k: {})
    ops = ops_application.create_app()
    store = Mock()
    store.states.return_value = [{"statistic_date": __import__("datetime").date(2026, 11, 18),
                                  "source_revision": 2, "published_source_revision": 2,
                                  "source_snapshot_at": None}]
    ops.state.monitoring = SimpleNamespace(store=store, zone=__import__("zoneinfo").ZoneInfo("UTC"))

    async def resolve(*args, **kwargs):
        return actor

    monkeypatch.setattr("gateway.application.resolve_identity", resolve)
    query = {"start_date": day, "end_date": day}
    routes = [
        ("GET", f"/nb/v1/monitoring/{suffix}", query) for suffix in (
            "models", "models/summary", "models/rankings", "models/trends",
            "skills", "skills/summary", "skills/rankings", "skills/trends",
            "agents", "agents/summary", "agents/trends", "agents/rankings",
            "mcp-tools", "mcp-tools/summary", "mcp-tools/rankings", "mcp-tools/trends",
            "mcp-tools/catalog", "mcp-tools/overview",
        )
    ]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ops), base_url="http://ops") as downstream:
        async def forward(request):
            response = await downstream.send(request)
            return httpx.Response(response.status_code, headers=response.headers,
                                  stream=httpx.ByteStream(response.content))

        edge = create_gateway_app(settings=GatewaySettings(signing_secret=secret, ops_url="http://ops"),
                                  transport=httpx.MockTransport(forward), identity_lookup=resolve)
        async with edge.router.lifespan_context(edge):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=edge), base_url="http://gateway") as client:
                for method, path, params in routes:
                    response = await client.request(method, path, params=params or None)
                    assert response.status_code == 200, (path, response.text)
                    assert set(response.json()) == {"message", "data", "requestId"}, path
                for domain in ("models", "skills", "mcp-tools"):
                    issued = await client.post(f"/nb/v1/monitoring/{domain}/refresh", json=query)
                    assert issued.status_code == 202, domain
                    token = issued.json()["data"]["data"]["refresh_id"]
                    status = await client.get(f"/nb/v1/monitoring/{domain}/refreshes/{token}")
                    assert status.status_code == 200, domain
                    assert set(status.json()) == {"message", "data", "requestId"}, domain
