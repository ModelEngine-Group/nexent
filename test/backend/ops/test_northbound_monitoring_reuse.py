# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Northbound /nb/ops monitoring mount: identity, envelope and drift guards.

The monitoring router is mounted twice: the browser session keeps the
internal contract, while the /nb mirror resolves API-key principals, locks
the tenant to the key's owner and wraps every response in the published
northbound envelope. These tests pin that lane; the session lane is pinned
by the existing monitoring suites.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import jwt
import pytest
from fastapi.testclient import TestClient

from contracts.authentication import AuthenticatedIdentity, CredentialKind
from contracts.errors.exceptions import LimitExceededError
from ops.api import application, monitoring
from ops.api.monitoring import OpsPrincipal, ops_principal

REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = REPO_ROOT / "backend" / "gateway" / "exposure" / "registry.json"

DAY = date(2026, 11, 17)


@pytest.fixture
def nb_client(monkeypatch):
    """An ops app whose /nb mount resolves one fixed API-key principal."""
    monkeypatch.setattr(application, "OPS_MONITORING_ENABLED", True)
    app = application.create_app()
    store = Mock()
    store.states.return_value = [
        {"statistic_date": DAY, "source_revision": 2, "published_source_revision": 2,
         "source_snapshot_at": None},
    ]
    app.state.monitoring = SimpleNamespace(store=store, zone=ZoneInfo("UTC"))
    identity = AuthenticatedIdentity(
        user_id="partner-user", tenant_id="tenantA", token_id=7, kind=CredentialKind.API_KEY,
    )
    app.dependency_overrides[ops_principal] = lambda: OpsPrincipal(kind="api_key", identity=identity)
    monkeypatch.setattr(monitoring, "JWT_SECRET", "isolated-nb-monitoring-jwt-secret")
    with TestClient(app) as client:
        yield client, store, identity


def _nb_refresh_token(client, tenant="tenantA", start=DAY, end=DAY, requested=None):
    response = client.post(
        "/nb/ops/v1/monitoring/models/refresh",
        json={"tenant_id": tenant, "start_date": start.isoformat(), "end_date": end.isoformat()},
    )
    return response


# ---------------------------------------------------------------------------
# Interface contract sweep: every route of the /nb/ops mirror, in the spirit
# of the legacy northbound suites (test_northbound_app.py) — one table, one
# envelope assertion per declared interface.
# ---------------------------------------------------------------------------

_COVERAGE = {"coverage_state": "covered", "is_stale": False, "data_as_of": None}
_TOKEN_USAGE = SimpleNamespace(agents={}, days={}, tokens={}, status=_COVERAGE)

_KERNEL_PATCHES = {
    "read_models": lambda *_a, **_k: ([], [], [DAY], _COVERAGE),
    "read_skills": lambda *_a, **_k: ([], [], [DAY], _COVERAGE),
    "read_agents": lambda *_a, **_k: ({}, _COVERAGE),
    "read_agent_views": lambda *_a, **_k: ([], 0, [], _COVERAGE),
    "read_agent_tokens": lambda *_a, **_k: _TOKEN_USAGE,
    "read_mcp_tools": lambda *_a, **_k: ([], [], [DAY], _COVERAGE),
    "mcp_server_catalog": lambda *_a, **_k: [],
    "mcp_services_by_tenant": lambda *_a, **_k: {},
}

# (method, path suffix, query params, json body) for every one of the 24 routes.
_INTERFACE_ROUTES = [
    ("GET", "models", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "models/summary", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "models/rankings", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "models/trends", {"start_date": DAY, "end_date": DAY}, None),
    ("POST", "models/refresh", None, {"start_date": DAY, "end_date": DAY}),
    ("GET", "skills", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "skills/summary", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "skills/rankings", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "skills/trends", {"start_date": DAY, "end_date": DAY}, None),
    ("POST", "skills/refresh", None, {"start_date": DAY, "end_date": DAY}),
    ("GET", "agents", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "agents/summary", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "agents/trends", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "agents/rankings", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "mcp-tools", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "mcp-tools/summary", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "mcp-tools/rankings", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "mcp-tools/trends", {"start_date": DAY, "end_date": DAY}, None),
    ("GET", "mcp-tools/catalog", {}, None),
    ("GET", "mcp-tools/overview", {"start_date": DAY, "end_date": DAY}, None),
    ("POST", "mcp-tools/refresh", None, {"start_date": DAY, "end_date": DAY}),
]


@pytest.mark.parametrize("method,suffix,params,json_body", _INTERFACE_ROUTES)
def test_nb_interface_contract_for_every_declared_route(
        nb_client, monkeypatch, method, suffix, params, json_body):
    """Each declared /nb/ops route answers in the partner envelope."""
    client, _, _ = nb_client
    for name, fake in _KERNEL_PATCHES.items():
        monkeypatch.setattr(monitoring, name, fake)
    params = {key: value.isoformat() if hasattr(value, "isoformat") else value
              for key, value in (params or {}).items()}
    json_body = {key: value.isoformat() if hasattr(value, "isoformat") else value
                 for key, value in (json_body or {}).items()} or None
    expected = 202 if method == "POST" else 200
    response = client.request(method, f"/nb/ops/v1/monitoring/{suffix}",
                              params=params or None, json=json_body)
    assert response.status_code == expected, response.text
    body = response.json()
    assert set(body) == {"message", "data", "requestId"}, body
    assert body["message"] == "success"
    assert body["requestId"]
    assert isinstance(body["data"], dict) and "data" in body["data"]


@pytest.mark.parametrize("domain", ["models", "skills", "mcp-tools"])
def test_nb_interface_refresh_status_round_trip(nb_client, monkeypatch, domain):
    """POST refresh issues a token; GET refreshes resolves it, both enveloped."""
    client, store, _ = nb_client
    for name, fake in _KERNEL_PATCHES.items():
        monkeypatch.setattr(monitoring, name, fake)
    issued = client.post(f"/nb/ops/v1/monitoring/{domain}/refresh",
                         json={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
    assert issued.status_code == 202
    token = issued.json()["data"]["data"]["refresh_id"]
    status = client.get(f"/nb/ops/v1/monitoring/{domain}/refreshes/{token}")
    assert status.status_code == 200
    body = status.json()
    assert set(body) == {"message", "data", "requestId"}
    assert body["data"]["data"]["status"] == "completed"


def test_nb_query_success_uses_the_partner_envelope(nb_client, monkeypatch):
    client, _, _ = nb_client
    monkeypatch.setattr(monitoring, "read_models", lambda *_args, **_kwargs: ([], [], [DAY],
                          {"coverage_state": "covered", "is_stale": False, "data_as_of": None}))
    response = client.get("/nb/ops/v1/monitoring/models/trends",
                          params={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "data", "requestId"}
    assert body["message"] == "success"
    assert body["requestId"]
    # The internal body (data + coverage fields) rides inside the envelope verbatim.
    assert set(body["data"]) == {"data", "coverage_state", "is_stale", "data_as_of"}
    assert body["data"]["data"][0]["statistic_date"] == DAY.isoformat()


def test_nb_query_locks_the_tenant_to_the_api_key_owner(nb_client, monkeypatch):
    client, _, identity = nb_client
    captured = {}

    def fake_read(_service, **kwargs):
        captured.update(kwargs)
        return [], [], [DAY], {"coverage_state": "covered", "is_stale": False, "data_as_of": None}

    monkeypatch.setattr(monitoring, "read_models", fake_read)
    params = {"start_date": DAY.isoformat(), "end_date": DAY.isoformat()}
    response = client.get("/nb/ops/v1/monitoring/models", params=params)
    assert response.status_code == 200
    assert captured["tenant"] == identity.tenant_id

    foreign = dict(params, tenant_id="tenantB")
    denied = client.get("/nb/ops/v1/monitoring/models", params=foreign)
    assert denied.status_code == 403
    body = denied.json()
    assert body["code"] == "HTTP_403"
    assert body["status"] == 403
    assert body["message"] == "Northbound monitoring is limited to the API key's tenant"
    assert body["requestId"]


def test_nb_refresh_issues_a_token_bound_to_the_identity_tenant(nb_client):
    client, _, identity = nb_client
    response = _nb_refresh_token(client)
    assert response.status_code == 202
    body = response.json()
    assert body["message"] == "success"
    token = body["data"]["data"]["refresh_id"]
    assert body["data"]["data"]["status"] == "queued"
    claims = jwt.decode(token, monitoring._refresh_key(), algorithms=["HS256"],
                        audience="ops-model-monitoring-refresh")
    assert claims["tenant"] == identity.tenant_id


def test_nb_refresh_status_hides_foreign_tenant_tokens(nb_client):
    client, _, _ = nb_client
    now = datetime.now(timezone.utc)
    foreign = jwt.encode({"aud": "ops-model-monitoring-refresh", "tenant": "tenantB",
                          "revisions": {DAY.isoformat(): 2}, "start": DAY.isoformat(),
                          "end": DAY.isoformat(), "requested": now.timestamp(),
                          "exp": now + timedelta(minutes=10)},
                         monitoring._refresh_key(), algorithm="HS256")
    response = client.get(f"/nb/ops/v1/monitoring/models/refreshes/{foreign}")
    assert response.status_code == 404
    assert response.json()["code"] == "HTTP_404"


def test_nb_refresh_status_resolves_own_tenant_tokens(nb_client):
    client, _, _ = nb_client
    token = _nb_refresh_token(client).json()["data"]["data"]["refresh_id"]
    response = client.get(f"/nb/ops/v1/monitoring/models/refreshes/{token}")
    assert response.status_code == 200
    assert response.json()["data"]["data"]["status"] == "completed"


def test_nb_refresh_records_audit_for_success_and_failure(nb_client, monkeypatch):
    client, store, identity = nb_client
    events = []
    monkeypatch.setattr("backend.http.server.security_audit.record_security_event",
                        lambda event, **kwargs: events.append((event, kwargs.get("result"))))
    _nb_refresh_token(client)
    assert events == [("northbound_monitoring_models_refresh", "success")]

    events.clear()
    store.states.side_effect = RuntimeError("offline")
    failed = _nb_refresh_token(client)
    assert failed.status_code == 503
    assert events == [("northbound_monitoring_models_refresh", "failed")]


def test_nb_refresh_actions_are_rate_limited_per_tenant(nb_client, monkeypatch):
    client, _, _ = nb_client

    async def exhausted(_tenant_id):
        raise LimitExceededError("Query rate exceeded limit. Please try again later")

    monkeypatch.setattr("backend.http.server.northbound.check_and_consume_rate_limit", exhausted)
    # The domain 429 travels the shared catch-all exception handler, which the
    # TestClient would re-raise by default; the probe only inspects the
    # delivered response, as the real client receives it.
    probe = TestClient(client.app, raise_server_exceptions=False)
    response = probe.post("/nb/ops/v1/monitoring/models/refresh",
                          json={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["status"] == 429


def test_nb_query_errors_keep_the_three_field_shape(nb_client, monkeypatch):
    client, _, _ = nb_client
    del client.app.state.monitoring
    response = client.get("/nb/ops/v1/monitoring/models",
                          params={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "HTTP_503"
    assert body["status"] == 503
    assert body["message"] == "Model monitoring is unavailable"


def test_nb_validation_errors_are_translated(nb_client):
    client, _, _ = nb_client
    far = DAY + timedelta(days=400)
    response = client.get("/nb/ops/v1/monitoring/models",
                          params={"start_date": DAY.isoformat(), "end_date": far.isoformat()})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "HTTP_422"
    assert body["status"] == 422


def test_nb_structured_conflict_detail_keeps_diagnostics(nb_client, monkeypatch):
    client, store, _, = nb_client
    store.states.return_value = [{"statistic_date": DAY, "source_revision": 2}]
    response = _nb_refresh_token(client, start=DAY - timedelta(days=1))
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "MONITORING_DATES_UNCOVERED"
    assert body["status"] == 409
    assert body["missing_dates"] == [(DAY - timedelta(days=1)).isoformat()]


def test_session_mount_keeps_the_internal_contract(nb_client, monkeypatch):
    client, _, _ = nb_client
    # Restore real principal resolution, then drive the session lane the way
    # the existing suites do: an authenticate dependency override.
    client.app.dependency_overrides.pop(ops_principal, None)
    client.app.dependency_overrides[monitoring.authenticate] = lambda: monitoring.CurrentUser(
        "operator", "tenantA", "OPS")
    monkeypatch.setattr(monitoring, "operations_scope",
                        lambda user, tenant, *_: tenant or user.tenant_id)
    try:
        monkeypatch.setattr(monitoring, "read_models", lambda *_args, **_kwargs: ([], [], [DAY],
                              {"coverage_state": "covered", "is_stale": False, "data_as_of": None}))
        response = client.get("/ops/v1/monitoring/models",
                              params={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"data", "coverage_state", "is_stale", "data_as_of"}
    finally:
        client.app.dependency_overrides.pop(monitoring.authenticate, None)


def test_registry_rows_match_nb_mounted_routes_and_capabilities(monkeypatch):
    """Drift guard: snapshot rows, /nb mount and capability ids stay one set."""
    mounted = set()
    for route in monitoring.ops_router.routes:
        # The application mounts ops_router a second time under /nb; FastAPI
        # wraps included routers, so the mirror is derived from the router
        # itself and confirmed behaviorally below.
        mounted.update((method, f"/nb{route.path}") for method in route.methods - {"HEAD"})
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    rows = [row for row in document["routes"] if row["path"].startswith("/nb/ops/v1/monitoring/")]
    registered = {(row["method"], row["path"]) for row in rows}
    assert registered == mounted
    assert len(rows) == 24
    capabilities = [row["capability_id"] for row in rows]
    assert len(set(capabilities)) == 24
    assert all(row["target"] == "ops" for row in rows)
    assert all(row["credential_kinds"] == ["api_key"] for row in rows)
    assert all(row["route_id"].startswith("route-") for row in rows)

    # The app keeps the /nb mirror mounted: an identity failure must stay
    # distinguishable from an unmounted route.
    monkeypatch.setattr(application, "OPS_MONITORING_ENABLED", True)
    with TestClient(application.create_app(), raise_server_exceptions=False) as probe:
        assert probe.get("/nb/ops/v1/monitoring/models").status_code != 404
