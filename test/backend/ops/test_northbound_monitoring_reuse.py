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
        "/nb/v1/monitoring/models/refresh",
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
    response = client.request(method, f"/nb/v1/monitoring/{suffix}",
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
    issued = client.post(f"/nb/v1/monitoring/{domain}/refresh",
                         json={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
    assert issued.status_code == 202
    token = issued.json()["data"]["data"]["refresh_id"]
    status = client.get(f"/nb/v1/monitoring/{domain}/refreshes/{token}")
    assert status.status_code == 200
    body = status.json()
    assert set(body) == {"message", "data", "requestId"}
    assert body["data"]["data"]["status"] == "completed"


def test_nb_query_success_uses_the_partner_envelope(nb_client, monkeypatch):
    client, _, _ = nb_client
    monkeypatch.setattr(monitoring, "read_models", lambda *_args, **_kwargs: ([], [], [DAY],
                          {"coverage_state": "covered", "is_stale": False, "data_as_of": None}))
    response = client.get("/nb/v1/monitoring/models/trends",
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
    response = client.get("/nb/v1/monitoring/models", params=params)
    assert response.status_code == 200
    assert captured["tenant"] == identity.tenant_id

    foreign = dict(params, tenant_id="tenantB")
    denied = client.get("/nb/v1/monitoring/models", params=foreign)
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
    response = client.get(f"/nb/v1/monitoring/models/refreshes/{foreign}")
    assert response.status_code == 404
    assert response.json()["code"] == "HTTP_404"


def test_nb_refresh_status_resolves_own_tenant_tokens(nb_client):
    client, _, _ = nb_client
    token = _nb_refresh_token(client).json()["data"]["data"]["refresh_id"]
    response = client.get(f"/nb/v1/monitoring/models/refreshes/{token}")
    assert response.status_code == 200
    assert response.json()["data"]["data"]["status"] == "completed"


def test_nb_refresh_actions_are_rate_limited_per_tenant(nb_client, monkeypatch):
    client, _, _ = nb_client

    async def exhausted(_tenant_id):
        raise LimitExceededError("Query rate exceeded limit. Please try again later")

    monkeypatch.setattr("backend.http.server.northbound.check_and_consume_rate_limit", exhausted)
    # The domain 429 travels the shared catch-all exception handler, which the
    # TestClient would re-raise by default; the probe only inspects the
    # delivered response, as the real client receives it.
    probe = TestClient(client.app, raise_server_exceptions=False)
    response = probe.post("/nb/v1/monitoring/models/refresh",
                          json={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["status"] == 429


def test_nb_query_errors_keep_the_three_field_shape(nb_client, monkeypatch):
    client, _, _ = nb_client
    del client.app.state.monitoring
    response = client.get("/nb/v1/monitoring/models",
                          params={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "HTTP_503"
    assert body["status"] == 503
    assert body["message"] == "Model monitoring is unavailable"


def test_nb_validation_errors_are_translated(nb_client):
    client, _, _ = nb_client
    far = DAY + timedelta(days=400)
    response = client.get("/nb/v1/monitoring/models",
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


# ---------------------------------------------------------------------------
# API-key usage accounting: same ledger, same writer, fail-open.
# ---------------------------------------------------------------------------

def test_accounting_shims_keep_one_definition():
    """Management re-exports point at the shared implementations, not copies."""
    from backend.http.server.northbound import record_api_key_usage as shared_record
    from infrastructure.rdb import token_usage as shared_module
    from management.db.identity import models as management_models
    from management.db.identity import token as management_token
    from management.services.permission.identity import northbound as management_northbound

    assert management_models.UserTokenUsageLog is shared_module.UserTokenUsageLog
    assert management_token.log_token_usage is shared_module.log_token_usage
    assert management_northbound.record_api_key_usage is shared_record
    # One table, registered once, on the shared base.
    assert shared_module.UserTokenUsageLog.__tablename__ == "user_token_usage_log_t"


def test_record_api_key_usage_writes_the_same_ledger_fields(monkeypatch):
    """The moved accounting keeps the exact ledger call, route template and fail-open."""
    from backend.http.server import northbound as shared

    captured = {}

    def fake_log(token_id, call_function_name, related_id, created_by, metadata):
        captured.update(token_id=token_id, call_function_name=call_function_name,
                        related_id=related_id, created_by=created_by, metadata=metadata)
        return 4242

    monkeypatch.setattr(shared, "log_token_usage", fake_log)
    request = SimpleNamespace(
        url=SimpleNamespace(path="/nb/v1/monitoring/models/summary"),
        method="GET", headers={"X-Request-Id": "req-42"},
        scope={"route": SimpleNamespace(path="/nb/v1/monitoring/models/summary")},
    )
    principal = AuthenticatedIdentity(user_id="partner-user", tenant_id="tenantA",
                                      token_id=7, kind=CredentialKind.API_KEY)
    shared.record_api_key_usage(principal, request)
    assert captured == {
        "token_id": 7,
        "call_function_name": "/nb/v1/monitoring/models/summary",
        "related_id": None,
        "created_by": "partner-user",
        "metadata": {"method": "GET", "request_id": "req-42",
                     "path": "/nb/v1/monitoring/models/summary"},
    }

    # No token id: nothing is written.
    captured.clear()
    shared.record_api_key_usage(
        AuthenticatedIdentity(user_id="u", tenant_id="t", kind=CredentialKind.API_KEY), request)
    assert captured == {}

    # Ledger failure never propagates (fail-open).
    def broken(*_args, **_kwargs):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(shared, "log_token_usage", broken)
    shared.record_api_key_usage(principal, request)  # no raise


def test_record_api_key_usage_skips_legacy_self_accounting_routes(monkeypatch):
    from backend.http.server import northbound as shared

    calls = []
    monkeypatch.setattr(shared, "log_token_usage", lambda **kwargs: calls.append(kwargs))
    principal = AuthenticatedIdentity(user_id="u", tenant_id="t", token_id=7,
                                      kind=CredentialKind.API_KEY)
    request = SimpleNamespace(url=SimpleNamespace(path="/nb/v1/chat/run"), method="POST",
                              headers={}, scope={})
    shared.record_api_key_usage(principal, request)
    assert calls == []


def test_nb_lane_accounts_usage_through_the_ops_lane(nb_client, monkeypatch):
    """A real /nb request resolves the trusted identity and queues the ledger write."""
    client, _, _ = nb_client
    submitted = []

    class Manager:
        def submit(self, lane, spec, fn, *args):
            submitted.append((lane, fn, args))

    client.app.state.thread_manager = Manager()
    record = {"kind": "api_key", "user_id": "partner-user", "tenant_id": "tenantA",
              "token_id": 7, "roles": []}
    monkeypatch.setattr(monitoring, "trusted_identity", lambda: record)
    client.app.dependency_overrides.pop(ops_principal, None)
    try:
        monkeypatch.setattr(monitoring, "read_models", lambda *_a, **_k: (
            [], [], [DAY], {"coverage_state": "covered", "is_stale": False, "data_as_of": None}))
        response = client.get("/nb/v1/monitoring/models/summary",
                              params={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
        assert response.status_code == 200
        assert response.json()["message"] == "success"
    finally:
        client.app.dependency_overrides[ops_principal] = None
        client.app.dependency_overrides.pop(ops_principal, None)
    assert len(submitted) == 1
    lane, fn, args = submitted[0]
    assert lane == "control-io"
    from backend.http.server.northbound import record_api_key_usage
    assert fn is record_api_key_usage
    principal, request = args
    assert (principal.user_id, principal.tenant_id, principal.token_id) == ("partner-user", "tenantA", 7)
    assert request.url.path == "/nb/v1/monitoring/models/summary"

    # Lane admission failure drops the accounting, never the request.
    class BrokenManager:
        def submit(self, *_args, **_kwargs):
            raise RuntimeError("lane full")

    client.app.state.thread_manager = BrokenManager()
    response = client.get("/nb/v1/monitoring/models/summary",
                          params={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
    assert response.status_code == 200


def test_nb_lane_without_gateway_identity_is_rejected(nb_client, monkeypatch):
    """No gateway-verified principal on /nb: 401, indistinguishable from unauthenticated."""
    client, _, _ = nb_client
    monkeypatch.setattr(monitoring, "trusted_identity", lambda: None)
    client.app.dependency_overrides.pop(ops_principal, None)
    try:
        # The domain 401 travels the shared catch-all handler; the probe only
        # inspects the delivered response, as the real client receives it.
        probe = TestClient(client.app, raise_server_exceptions=False)
        response = probe.get("/nb/v1/monitoring/models/summary",
                             params={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
        assert response.status_code == 401
        body = response.json()
        assert body["status"] == 401
    finally:
        client.app.dependency_overrides.pop(ops_principal, None)


def test_nb_lane_rejects_a_session_kind_gateway_identity(nb_client, monkeypatch):
    client, _, _ = nb_client
    monkeypatch.setattr(monitoring, "trusted_identity",
                        lambda: {"kind": "session", "user_id": "u", "tenant_id": "t"})
    client.app.dependency_overrides.pop(ops_principal, None)
    try:
        probe = TestClient(client.app, raise_server_exceptions=False)
        response = probe.get("/nb/v1/monitoring/models/summary",
                             params={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
        assert response.status_code == 401
    finally:
        client.app.dependency_overrides.pop(ops_principal, None)


# ---------------------------------------------------------------------------
# Middleware and shared-layer defensive paths (codecov patch coverage).
# ---------------------------------------------------------------------------

def test_error_body_falls_back_to_a_phrase_for_unknown_status():
    from backend.ops.api.northbound_envelope import _error_body

    body = _error_body(None, 419, "req-1")
    assert body == {"code": "HTTP_419", "message": "Request failed", "status": 419,
                    "requestId": "req-1"}
    phrase = _error_body({}, 503, "req-2")
    assert phrase["message"] == "Service Unavailable"


@pytest.mark.asyncio
async def test_envelope_middleware_passes_non_json_and_undecodable_bodies_through():
    from backend.ops.api.northbound_envelope import NorthboundEnvelopeMiddleware

    async def drive(app, *, content_type, body):
        sent = []
        scope = {"type": "http", "path": "/nb/v1/monitoring/models",
                 "method": "GET", "headers": [], "query_string": b""}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await app(scope, receive, send)
        return sent

    async def text_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"plain-bytes"})

    sent = await drive(NorthboundEnvelopeMiddleware(text_app), content_type=b"text/plain",
                       body=b"plain-bytes")
    assert sent[-1]["body"] == b"plain-bytes"  # passthrough, not enveloped

    async def undecodable_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b"\xff\xfe not-json"})

    sent = await drive(NorthboundEnvelopeMiddleware(undecodable_app),
                       content_type=b"application/json", body=b"\xff\xfe not-json")
    assert sent[-1]["body"] == b"\xff\xfe not-json"


@pytest.mark.asyncio
async def test_envelope_middleware_reassembles_chunked_bodies_and_forwards_other_messages():
    from backend.ops.api.northbound_envelope import NorthboundEnvelopeMiddleware

    sent = []
    forwarded = []

    async def chunked_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"data"', "more_body": True})
        await send({"type": "http.response.trailers", "headers": []})
        await send({"type": "http.response.body", "body": b': 1}'})

    async def send(message):
        if message["type"] == "http.response.trailers":
            forwarded.append(message)
            return
        sent.append(message)

    scope = {"type": "http", "path": "/nb/v1/monitoring/models",
             "method": "GET", "headers": [], "query_string": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    await NorthboundEnvelopeMiddleware(chunked_app)(scope, receive, send)
    assert forwarded and forwarded[0]["type"] == "http.response.trailers"
    body = json.loads(sent[-1]["body"])
    assert body["data"] == {"data": 1} and body["message"] == "success" and body["requestId"]


def test_audit_helpers_cover_the_fail_open_paths():
    from backend.http.server import security_audit

    assert security_audit._compact(None) == ""
    entry = security_audit.format_audit_entry(
        "evt", user_id="u", tenant_id="t", details={"unserializable": object()})
    assert "unserializable" in entry
    # A request whose attribute access raises takes the never-raises path.
    class Broken:
        @property
        def headers(self):
            raise RuntimeError("boom")

    security_audit.record_security_event("evt", request=Broken(), user_id="u", tenant_id="t")


@pytest.mark.asyncio
async def test_rate_limit_degrades_to_process_memory_without_the_redis_adapter(monkeypatch):
    import sys as sys_module

    from backend.http.server import northbound as shared

    # A None entry makes the lazy import raise ImportError: the adapter is
    # treated as unavailable and the in-process bucket keeps protecting.
    monkeypatch.setitem(sys_module.modules, "infrastructure.redis.run_state", None)
    await shared.check_and_consume_rate_limit("tenant-adapter-missing")
    assert shared._RATE_STATE["tenant-adapter-missing"]


def test_record_usage_skips_legacy_self_accounting_paths(monkeypatch):
    from backend.http.server import northbound as shared

    calls = []
    monkeypatch.setattr(shared, "log_token_usage", lambda **kw: calls.append(kw))
    principal = AuthenticatedIdentity(user_id="u", tenant_id="t", token_id=7,
                                      kind=CredentialKind.API_KEY)
    shared.record_api_key_usage(
        principal, SimpleNamespace(url=SimpleNamespace(path="/nb/v1/chat/stop/abc"),
                                   method="GET", headers={}, scope={}))
    shared.record_api_key_usage(
        principal, SimpleNamespace(url=SimpleNamespace(path="/nb/v1/conversations/1/title"),
                                   method="PUT", headers={}, scope={}))
    assert calls == []


def test_token_usage_resolves_the_session_factory_lazily(monkeypatch):
    """The registry stays client-free at import; the factory binds on first write."""
    from infrastructure.rdb import token_usage

    monkeypatch.setattr(token_usage, "get_db_session", None)
    factory = token_usage._resolve_session_factory()
    from infrastructure.rdb.client import get_db_session
    assert factory is get_db_session
    assert token_usage.get_db_session is get_db_session


# ---------------------------------------------------------------------------
# Remaining codecov patch lines: identity, audit fail-open, refresh guards,
# per-domain foreign-token 404s, and error-body extras.
# ---------------------------------------------------------------------------

def test_nb_lane_rejects_an_incomplete_gateway_identity(nb_client, monkeypatch):
    client, _, _ = nb_client
    monkeypatch.setattr(monitoring, "trusted_identity", lambda: {"kind": "api_key"})
    client.app.dependency_overrides.pop(ops_principal, None)
    try:
        probe = TestClient(client.app, raise_server_exceptions=False)
        response = probe.get("/nb/v1/monitoring/models/summary",
                             params={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
        assert response.status_code == 401
    finally:
        client.app.dependency_overrides.pop(ops_principal, None)


def test_nb_refresh_rejects_an_invalid_date_range(nb_client):
    client, _, _ = nb_client
    far = DAY + timedelta(days=400)
    response = client.post("/nb/v1/monitoring/models/refresh",
                           json={"start_date": DAY.isoformat(), "end_date": far.isoformat()})
    assert response.status_code == 422
    assert response.json()["status"] == 422


def test_nb_refresh_reports_unavailable_without_the_service(nb_client):
    client, _, _ = nb_client
    del client.app.state.monitoring
    response = client.post("/nb/v1/monitoring/models/refresh",
                           json={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
    assert response.status_code == 503
    assert response.json()["status"] == 503


@pytest.mark.parametrize("domain", ["skills", "mcp-tools"])
def test_nb_refresh_status_hides_foreign_tokens_in_every_domain(nb_client, domain):
    client, _, _ = nb_client
    now = datetime.now(timezone.utc)
    if domain == "skills":
        key, audience = monitoring._refresh_key("skill"), "ops-skill-monitoring-refresh"
    else:
        key, audience = monitoring._tool_refresh_key(), "ops-mcp-tool-monitoring-refresh"
    foreign = jwt.encode({"aud": audience, "tenant": "tenantB", "revisions": {},
                          "start": DAY.isoformat(), "end": DAY.isoformat(),
                          "requested": now.timestamp(), "exp": now + timedelta(minutes=10)},
                         key, algorithm="HS256")
    response = client.get(f"/nb/v1/monitoring/{domain}/refreshes/{foreign}")
    assert response.status_code == 404
    assert response.json()["code"] == "HTTP_404"


def test_error_body_preserves_top_level_code_and_extras():
    from backend.ops.api.northbound_envelope import _error_body

    body = _error_body({"code": "RATE_LIMIT_EXCEEDED", "message": "slow down",
                        "retryable": True}, 429, "req-x")
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["retryable"] is True
    assert body["status"] == 429 and body["requestId"] == "req-x"


def test_audit_record_survives_a_broken_logger(monkeypatch):
    from backend.http.server import security_audit

    class BrokenLogger:
        def error(self, *_args, **_kwargs):
            raise RuntimeError("logging pipeline down")

    monkeypatch.setattr(security_audit, "logger", BrokenLogger())

    class BrokenRequest:
        @property
        def headers(self):
            raise RuntimeError("boom")

    security_audit.record_security_event("evt", request=BrokenRequest(),
                                         user_id="u", tenant_id="t")


def test_record_api_key_usage_records_gate_templates_verbatim(monkeypatch):
    """Gate routers embed their prefix in route.path; the ledger records it as-is.

    The include_router mount shape that once produced un-prefixed templates is
    gone (gates own their /nb/v1 prefix), so verbatim recording is both the
    real behavior and the published contract.
    """
    from backend.http.server import northbound as shared

    captured = {}
    monkeypatch.setattr(shared, "log_token_usage",
                        lambda **kw: captured.update(kw))
    principal = AuthenticatedIdentity(user_id="u", tenant_id="t", token_id=7,
                                      kind=CredentialKind.API_KEY)
    request = SimpleNamespace(
        url=SimpleNamespace(path="/nb/v1/monitoring/models/refreshes/<jwt>"),
        method="GET", headers={},
        scope={"route": SimpleNamespace(path="/nb/v1/monitoring/models/refreshes/{refresh_id}")},
    )
    shared.record_api_key_usage(principal, request)
    assert captured["call_function_name"] ==         "/nb/v1/monitoring/models/refreshes/{refresh_id}"

    # Management-style routes already embed their prefix: also verbatim.
    captured.clear()
    request = SimpleNamespace(
        url=SimpleNamespace(path="/nb/v1/automations"),
        method="GET", headers={},
        scope={"route": SimpleNamespace(path="/nb/v1/automations")},
    )
    shared.record_api_key_usage(principal, request)
    assert captured["call_function_name"] == "/nb/v1/automations"


def test_session_lane_refresh_skips_the_rate_limit_guard(nb_client, monkeypatch):
    """The guard is northbound-only: a session refresh is never throttled."""
    client, _, _ = nb_client
    client.app.dependency_overrides.pop(ops_principal, None)
    client.app.dependency_overrides[monitoring.authenticate] = lambda: monitoring.CurrentUser(
        "operator", "tenantA", "OPS")
    monkeypatch.setattr(monitoring, "operations_scope",
                        lambda user, tenant, *_: tenant or user.tenant_id)
    try:
        response = client.post("/ops/v1/monitoring/models/refresh",
                               json={"start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
        assert response.status_code == 202
        # Internal contract: bare data body, no partner envelope.
        assert response.json()["data"]["status"] == "queued"
        assert set(response.json()) == {"data"}
    finally:
        client.app.dependency_overrides.pop(monitoring.authenticate, None)


@pytest.mark.asyncio
async def test_action_guard_throttles_only_api_key_principals(monkeypatch):
    """Guard contract: northbound actions are throttled, session callers are not."""
    calls = []

    async def fake_limit(tenant_id):
        calls.append(tenant_id)

    monkeypatch.setattr("backend.http.server.northbound.check_and_consume_rate_limit", fake_limit)
    session_principal = OpsPrincipal(kind="session", user=monitoring.CurrentUser("op", "t", "OPS"))
    await monitoring.nb_action_guard(None, session_principal)
    assert calls == []  # session lane never throttled

    key_principal = OpsPrincipal(kind="api_key", identity=AuthenticatedIdentity(
        user_id="u", tenant_id="tenantA", token_id=7, kind=CredentialKind.API_KEY))
    await monitoring.nb_action_guard(None, key_principal)
    assert calls == ["tenantA"]
