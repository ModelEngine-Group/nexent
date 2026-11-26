# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""MCP tool monitoring API: service/tool views and the signed refresh lifecycle."""

from base64 import urlsafe_b64encode
from datetime import date, datetime, timedelta, timezone
from struct import pack
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import jwt
import pytest
from fastapi.testclient import TestClient

from management.services.permission.identity.session import authenticate
from ops.api import application, monitoring
from permissions.models import CurrentUser
from test.backend.ops.test_monitoring_api import monitoring_client


def _tool_rows():
    return [
        {"tenant_id": "tenant", "mcp_server_id": 3, "mcp_server_name": "docs", "mcp_server_type": "container",
         "tool_name": "search_docs", "statistic_date": "2026-11-17", "request_count": 2, "error_count": 1,
         "error_eligible_count": 2, "duration_ms_sum": 60, "duration_ms_sample_count": 2},
        {"tenant_id": "tenant", "mcp_server_id": 4, "mcp_server_name": "other", "mcp_server_type": "remote",
         "tool_name": "translate", "statistic_date": "2026-11-17", "request_count": 1, "error_count": 0,
         "error_eligible_count": 1, "duration_ms_sum": 10, "duration_ms_sample_count": 1},
    ]


def _tool_status(**overrides):
    return {"data_as_of": None, "coverage_state": "partial", "is_stale": False, **overrides}


def test_mcp_tools_list_returns_sorted_searchable_items(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: (_tool_rows(), [], [date(2026, 11, 17)], _tool_status()))

    response = client.get("/ops/v1/monitoring/mcp-tools",
                          params={"start_date": "2026-11-17", "end_date": "2026-11-17",
                                  "dimension": "tools"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 2
    assert [item["tool_name"] for item in data["items"]] == ["search_docs", "translate"]
    assert data["items"][0]["metrics"]["avg_duration_ms"] == 30
    assert response.json()["coverage_state"] == "partial"

    searched = client.get("/ops/v1/monitoring/mcp-tools",
                          params={"start_date": "2026-11-17", "end_date": "2026-11-17",
                                  "dimension": "tools", "search": "trans"})
    assert [item["tool_name"] for item in searched.json()["data"]["items"]] == ["translate"]

    paginated = client.get("/ops/v1/monitoring/mcp-tools",
                           params={"start_date": "2026-11-17", "end_date": "2026-11-17",
                                   "dimension": "tools", "page": 2, "page_size": 1})
    assert paginated.json()["data"]["total"] == 2
    assert [item["tool_name"] for item in paginated.json()["data"]["items"]] == ["translate"]


def test_mcp_tools_summary_keeps_uncovered_windows_none(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    params = {"start_date": "2026-11-17", "end_date": "2026-11-17"}
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: ([], [], [], _tool_status(coverage_state="uncovered")))

    uncovered = client.get("/ops/v1/monitoring/mcp-tools/summary", params=params)
    assert uncovered.json()["data"] == {"service_count": 0, "active_services": 0, "tool_count": 0,
                                       "active_tools": 0, "request_count": None, "error_count": None,
                                       "error_eligible_count": None, "error_rate": None, "avg_duration_ms": None}

    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: (_tool_rows(), [], [date(2026, 11, 17)], _tool_status()))
    covered = client.get("/ops/v1/monitoring/mcp-tools/summary", params=params)
    assert covered.json()["data"]["tool_count"] == 2
    assert covered.json()["data"]["request_count"] == 3
    assert covered.json()["data"]["error_rate"] == 1 / 3
    assert covered.json()["data"]["avg_duration_ms"] == 70 / 3


def test_mcp_tools_trends_keep_missing_dates_separate_from_zero_days(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: (_tool_rows()[:1], [], [date(2026, 11, 17)], _tool_status()))

    response = client.get("/ops/v1/monitoring/mcp-tools/trends",
                          params={"start_date": "2026-11-16", "end_date": "2026-11-17"})
    assert response.status_code == 200
    missing, covered = response.json()["data"]
    assert missing["statistic_date"] == "2026-11-16"
    assert all(value is None for key, value in missing.items() if key != "statistic_date")
    assert covered["statistic_date"] == "2026-11-17"
    assert covered["request_count"] == 2
    assert covered["error_rate"] == 0.5


def test_mcp_tools_rankings_top_items_by_metric(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    rows = _tool_rows() + [
        {"tenant_id": "tenant", "mcp_server_id": 5, "mcp_server_name": "extra", "mcp_server_type": "builtin",
         "tool_name": "summarize", "statistic_date": "2026-11-17", "request_count": 7, "error_count": 0,
         "error_eligible_count": 7, "duration_ms_sum": 70, "duration_ms_sample_count": 7},
    ]
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: (rows, [], [date(2026, 11, 17)], _tool_status()))

    response = client.get("/ops/v1/monitoring/mcp-tools/rankings",
                          params={"start_date": "2026-11-17", "end_date": "2026-11-17",
                                  "dimension": "tools"})
    assert response.status_code == 200
    assert [item["tool_name"] for item in response.json()["data"]] == ["summarize", "search_docs", "translate"]

    durations = client.get("/ops/v1/monitoring/mcp-tools/rankings",
                           params={"start_date": "2026-11-17", "end_date": "2026-11-17",
                                   "dimension": "tools", "metric": "avg_duration_ms"})
    assert [item["tool_name"] for item in durations.json()["data"]] == ["search_docs", "translate", "summarize"]


def test_mcp_tool_refresh_conflicts_then_completes(monitoring_client):
    client, store = monitoring_client
    day = date(2026, 11, 17)
    store.states.return_value = [{"statistic_date": day, "source_revision": 2, "published_source_revision": 1,
                                  "source_snapshot_at": None}]

    conflict = client.post("/ops/v1/monitoring/mcp-tools/refresh",
                           json={"start_date": "2026-11-16", "end_date": day.isoformat()})
    assert conflict.status_code == 409
    assert conflict.json()["message"] == {"code": "MONITORING_DATES_UNCOVERED", "missing_dates": ["2026-11-16"]}

    response = client.post("/ops/v1/monitoring/mcp-tools/refresh",
                           json={"start_date": day.isoformat(), "end_date": day.isoformat()})
    assert response.status_code == 202
    path = f"/ops/v1/monitoring/mcp-tools/refreshes/{response.json()['data']['refresh_id']}"
    assert client.get(path).json()["data"]["status"] == "running"
    store.states.return_value[0]["published_source_revision"] = 2
    assert client.get(path).json()["data"]["status"] == "completed"


def test_mcp_tool_refresh_token_is_isolated_from_the_model_audience(monitoring_client):
    client, _ = monitoring_client
    day = date(2026, 11, 17)
    now = datetime.now(timezone.utc)
    model_token = jwt.encode({"aud": "ops-model-monitoring-refresh", "tenant": "tenant", "revisions": {},
                              "start": day.isoformat(), "end": day.isoformat(), "requested": now.timestamp(),
                              "exp": now + timedelta(minutes=1)}, monitoring._refresh_key(), algorithm="HS256")
    response = client.get(f"/ops/v1/monitoring/mcp-tools/refreshes/{model_token}")
    assert response.status_code == 404


def test_mcp_tools_list_defaults_to_service_dimension(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    rows = [
        {"tenant_id": "tenant", "mcp_server_id": 3, "mcp_server_name": "beta", "mcp_server_type": "remote",
         "tool_name": "translate", "request_count": 1, "error_count": 0, "error_eligible_count": 1,
         "duration_ms_sum": 10, "duration_ms_sample_count": 1},
        {"tenant_id": "tenant", "mcp_server_id": 4, "mcp_server_name": "alpha", "mcp_server_type": "container",
         "tool_name": "search_docs", "request_count": 2, "error_count": 0, "error_eligible_count": 2,
         "duration_ms_sum": 40, "duration_ms_sample_count": 2},
        {"tenant_id": "tenant", "mcp_server_id": 4, "mcp_server_name": "alpha", "mcp_server_type": "container",
         "tool_name": "summarize", "request_count": 3, "error_count": 3, "error_eligible_count": 3,
         "duration_ms_sum": 60, "duration_ms_sample_count": 3},
    ]
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: (rows, [], [date(2026, 11, 17)], _tool_status()))

    response = client.get("/ops/v1/monitoring/mcp-tools",
                          params={"start_date": "2026-11-17", "end_date": "2026-11-17"})
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert response.json()["data"]["total"] == 2
    assert items[0]["mcp_server_name"] == "alpha"
    assert items[0]["active_tools"] == 2
    assert items[0]["metrics"]["request_count"] == 5
    assert items[1]["mcp_server_name"] == "beta"

    explicit_tools = client.get("/ops/v1/monitoring/mcp-tools",
                                params={"start_date": "2026-11-17", "end_date": "2026-11-17",
                                        "dimension": "tools"})
    assert explicit_tools.json()["data"]["total"] == 3
    assert "active_tools" not in explicit_tools.json()["data"]["items"][0]


def test_mcp_tools_summary_reports_service_and_tool_activity(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    rows = [
        {"tenant_id": "tenant", "mcp_server_id": 3, "mcp_server_name": "docs", "mcp_server_type": "container",
         "tool_name": "search_docs", "request_count": 2, "error_count": 0, "error_eligible_count": 2,
         "duration_ms_sum": 20, "duration_ms_sample_count": 2},
        {"tenant_id": "tenant", "mcp_server_id": 3, "mcp_server_name": "docs", "mcp_server_type": "container",
         "tool_name": "translate", "request_count": 1, "error_count": 1, "error_eligible_count": 1,
         "duration_ms_sum": 10, "duration_ms_sample_count": 1},
    ]
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: (rows, [], [date(2026, 11, 17)], _tool_status()))

    response = client.get("/ops/v1/monitoring/mcp-tools/summary",
                          params={"start_date": "2026-11-17", "end_date": "2026-11-17"})
    data = response.json()["data"]
    assert data["service_count"] == 1
    assert data["active_services"] == 1
    assert data["tool_count"] == 2
    assert data["active_tools"] == 2
    assert data["request_count"] == 3


def test_mcp_tools_list_keeps_registered_never_called_servers(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    rows = [
        {"tenant_id": "tenant", "mcp_server_id": 3, "mcp_server_name": "docs", "mcp_server_type": "container",
         "tool_name": "search_docs", "statistic_date": "2026-11-17", "request_count": 2, "error_count": 0,
         "error_eligible_count": 2, "duration_ms_sum": 20, "duration_ms_sample_count": 2},
    ]
    inventory = [
        {"tenant_id": "tenant", "mcp_server_id": 3, "mcp_server_name": "docs", "mcp_server_type": "container"},
        {"tenant_id": "tenant", "mcp_server_id": 9, "mcp_server_name": "idle", "mcp_server_type": "remote"},
    ]
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: (rows, inventory, [date(2026, 11, 17)], _tool_status()))
    params = {"start_date": "2026-11-17", "end_date": "2026-11-17"}

    listed = client.get("/ops/v1/monitoring/mcp-tools", params=params).json()["data"]
    assert [item["mcp_server_name"] for item in listed["items"]] == ["docs", "idle"]
    # Partial coverage keeps unknown metrics instead of zeroing them; missing rows sort last.
    assert listed["items"][0]["metrics"]["request_count"] == 2
    assert listed["items"][1]["metrics"]["request_count"] is None
    assert listed["items"][1]["active_tools"] is None

    summary = client.get("/ops/v1/monitoring/mcp-tools/summary", params=params).json()["data"]
    assert summary["service_count"] == 2 and summary["active_services"] == 1
    assert summary["request_count"] == 2

    rankings = client.get("/ops/v1/monitoring/mcp-tools/rankings", params=params).json()["data"]
    assert [item["mcp_server_name"] for item in rankings] == ["docs"]

    covered_status = {"data_as_of": None, "coverage_state": "covered", "is_stale": False}
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: (rows, inventory, [date(2026, 11, 17)], covered_status))
    items = client.get("/ops/v1/monitoring/mcp-tools", params=params).json()["data"]["items"]
    # Covered windows report definitive zero counters for never-called servers.
    assert items[1]["metrics"]["request_count"] == 0
    assert items[1]["metrics"]["error_rate"] is None


def test_mcp_tools_rankings_service_dimension_top5(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    rows = [
        {"tenant_id": "tenant", "mcp_server_id": n, "mcp_server_name": f"svc{n}", "mcp_server_type": "remote",
         "tool_name": "tool", "request_count": n, "error_count": 0, "error_eligible_count": n,
         "duration_ms_sum": n, "duration_ms_sample_count": 1}
        for n in range(1, 8)
    ]
    # A multi-tool server must aggregate before ranking (tool-level rows would not).
    rows.append({"tenant_id": "tenant", "mcp_server_id": 6, "mcp_server_name": "svc6", "mcp_server_type": "remote",
                 "tool_name": "extra_tool", "request_count": 2, "error_count": 0, "error_eligible_count": 2,
                 "duration_ms_sum": 2, "duration_ms_sample_count": 2})
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: (rows, [], [date(2026, 11, 17)], _tool_status()))

    response = client.get("/ops/v1/monitoring/mcp-tools/rankings",
                          params={"start_date": "2026-11-17", "end_date": "2026-11-17"})
    assert response.status_code == 200
    ranking = response.json()["data"]
    assert len(ranking) == 5
    assert [item["mcp_server_name"] for item in ranking] == ["svc6", "svc7", "svc5", "svc4", "svc3"]
    assert ranking[0]["metrics"]["request_count"] == 8  # 6 + 2 merged across tools


def test_mcp_tools_pass_tool_name_filter_to_the_reader(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    captured = {}

    def fake_read(*args, **kwargs):
        captured.update(kwargs)
        return ([], [], [], _tool_status())

    monkeypatch.setattr(monitoring, "read_mcp_tools", fake_read)
    client.get("/ops/v1/monitoring/mcp-tools",
               params={"start_date": "2026-11-17", "end_date": "2026-11-17",
                       "dimension": "tools", "tool_name": "search_docs"})
    assert captured["tool_name"] == "search_docs"


def test_mcp_tools_catalog_scopes_to_the_requested_tenant(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    captured = {}

    def fake_catalog(tenant, groups=None):
        captured["args"] = (tenant, groups)
        return [{"service_id": 3, "name": "docs", "type": "container"}] if tenant == "tenant" else []

    monkeypatch.setattr(monitoring, "mcp_server_catalog", fake_catalog)

    response = client.get("/ops/v1/monitoring/mcp-tools/catalog")
    assert response.status_code == 200
    assert response.json()["data"] == [{"service_id": 3, "name": "docs", "type": "container"}]
    assert captured["args"] == ("tenant", None)

    other = client.get("/ops/v1/monitoring/mcp-tools/catalog", params={"tenant_id": "elsewhere"})
    assert other.json()["data"] == []
    assert captured["args"] == ("elsewhere", None)

    # The dropdown refresh passes the selected group through to the catalog.
    grouped = client.get("/ops/v1/monitoring/mcp-tools/catalog",
                         params=[("group_ids", 5), ("group_ids", 7)])
    assert grouped.status_code == 200
    assert captured["args"] == ("tenant", [5, 7])
    assert client.get("/ops/v1/monitoring/mcp-tools/catalog",
                      params={"group_ids": 0}).status_code == 422


def test_mcp_tools_overview_aggregates_platform_trend_and_per_tenant_inventory(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    rows = [
        {"tenant_id": "tenant", "mcp_server_id": 3, "tool_name": "search_docs",
         "statistic_date": "2026-11-17", "request_count": 5, "error_count": 0, "error_eligible_count": 5,
         "duration_ms_sum": 50, "duration_ms_sample_count": 5},
        {"tenant_id": "other", "mcp_server_id": 9, "tool_name": "translate",
         "statistic_date": "2026-11-17", "request_count": 7, "error_count": 1, "error_eligible_count": 7,
         "duration_ms_sum": 70, "duration_ms_sample_count": 7},
    ]

    def fake_read(*args, **kwargs):
        captured["tenant"] = kwargs.get("tenant")
        return (rows if captured["tenant"] is None else
                [row for row in rows if row["tenant_id"] == captured["tenant"]],
                [], [date(2026, 11, 17)], _tool_status())

    captured = {}
    monkeypatch.setattr(monitoring, "read_mcp_tools", fake_read)
    monkeypatch.setattr(monitoring, "operations_scope", lambda user, tenant, *_: tenant)
    monkeypatch.setattr(monitoring, "mcp_services_by_tenant",
                        lambda tenant: [{"tenant_id": "tenant", "service_count": 2},
                                        {"tenant_id": "other", "service_count": 1}])

    response = client.get("/ops/v1/monitoring/mcp-tools/overview",
                          params={"start_date": "2026-11-16", "end_date": "2026-11-17"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert captured["tenant"] is None
    assert data["services_by_tenant"] == [{"tenant_id": "tenant", "service_count": 2},
                                          {"tenant_id": "other", "service_count": 1}]
    missing, covered = data["calls_trend"]
    assert missing["statistic_date"] == "2026-11-16"
    assert missing["request_count"] is None
    assert covered["statistic_date"] == "2026-11-17"
    assert covered["request_count"] == 12
    assert response.json()["coverage_state"] == "partial"


def _bare_monitoring_client(monkeypatch):
    """A monitoring app without a bound monitoring service, for unavailable paths."""
    monkeypatch.setattr(application, "OPS_MONITORING_ENABLED", True)
    app = application.create_app()
    app.dependency_overrides[authenticate] = lambda: CurrentUser("operator", "tenant", "OPS")
    monkeypatch.setattr(monitoring, "operations_scope", lambda user, tenant, *_: tenant or user.tenant_id)
    monkeypatch.setattr(monitoring, "JWT_SECRET", "isolated-monitoring-jwt-secret-for-tests")
    return TestClient(app)


def _tool_token(**overrides):
    now = datetime.now(timezone.utc)
    payload = {"aud": "ops-mcp-tool-monitoring-refresh", "tenant": "tenant", "revisions": {},
               "start": "2026-11-17", "end": "2026-11-17", "requested": now.timestamp(),
               "exp": now + timedelta(minutes=1)}
    payload.update(overrides)
    return jwt.encode(payload, monitoring._tool_refresh_key(), algorithm="HS256")


def test_mcp_tool_selection_rejects_invalid_ranges(monitoring_client):
    client, _ = monitoring_client
    response = client.get("/ops/v1/monitoring/mcp-tools",
                          params={"start_date": "2026-11-18", "end_date": "2026-11-17"})
    assert response.status_code == 422


def test_mcp_tool_selection_rejects_unknown_server_type(monitoring_client):
    """server_type accepts only the fact contract's normalized values."""
    client, _ = monitoring_client
    response = client.get("/ops/v1/monitoring/mcp-tools",
                          params={"start_date": "2026-11-17", "end_date": "2026-11-17",
                                  "server_type": "serverless"})
    assert response.status_code == 422


def test_mcp_tool_selection_accepts_builtin_server_type(monitoring_client, monkeypatch):
    """The synthesized tenant-local endpoint is selectable through its type."""
    client, _ = monitoring_client
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        Mock(return_value=([], [], [], {"coverage_state": "uncovered", "is_stale": False,
                                                        "data_as_of": None})))
    response = client.get("/ops/v1/monitoring/mcp-tools",
                          params={"start_date": "2026-11-17", "end_date": "2026-11-17",
                                  "server_type": "builtin"})
    assert response.status_code == 200
    assert monitoring.read_mcp_tools.call_args.kwargs["server_type"] == "builtin"


def test_mcp_tools_require_an_available_monitoring_service(monitoring_client, monkeypatch):
    monkeypatch.setattr(monitoring, "read_mcp_tools", Mock(side_effect=RuntimeError("store down")))
    response = monitoring_client[0].get("/ops/v1/monitoring/mcp-tools",
                                        params={"start_date": "2026-11-17", "end_date": "2026-11-17"})
    assert response.status_code == 503
    assert response.json()["message"] == "MCP tool monitoring is temporarily unavailable"

    bare = _bare_monitoring_client(monkeypatch)
    assert bare.get("/ops/v1/monitoring/mcp-tools",
                    params={"start_date": "2026-11-17", "end_date": "2026-11-17"}).status_code == 503
    assert bare.get("/ops/v1/monitoring/mcp-tools/summary",
                    params={"start_date": "2026-11-17", "end_date": "2026-11-17"}).status_code == 503


def test_mcp_tool_refresh_rejects_invalid_scope(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    reversed_range = client.post("/ops/v1/monitoring/mcp-tools/refresh",
                                 json={"start_date": "2026-11-18", "end_date": "2026-11-17"})
    assert reversed_range.status_code == 422

    monkeypatch.setattr(monitoring, "operations_scope", lambda user, tenant, *_: None)
    response = client.post("/ops/v1/monitoring/mcp-tools/refresh",
                           json={"start_date": "2026-11-17", "end_date": "2026-11-17"})
    assert response.status_code == 422


def test_mcp_tool_refresh_requires_service_and_secret(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    scope = {"start_date": "2026-11-17", "end_date": "2026-11-17"}

    monkeypatch.setattr(monitoring, "JWT_SECRET", "")
    assert client.post("/ops/v1/monitoring/mcp-tools/refresh", json=scope).status_code == 503

    bare = _bare_monitoring_client(monkeypatch)
    assert bare.post("/ops/v1/monitoring/mcp-tools/refresh", json=scope).status_code == 503


def test_mcp_tool_refresh_reports_store_failure_as_temporarily_unavailable(monitoring_client):
    client, store = monitoring_client
    store.states.side_effect = RuntimeError("store down")
    response = client.post("/ops/v1/monitoring/mcp-tools/refresh",
                           json={"start_date": "2026-11-17", "end_date": "2026-11-17"})
    assert response.status_code == 503
    assert response.json()["message"] == "MCP tool monitoring refresh is temporarily unavailable"


def test_mcp_tool_refresh_status_requires_service_and_secret(monitoring_client, monkeypatch):
    client, _ = monitoring_client

    monkeypatch.setattr(monitoring, "JWT_SECRET", "")
    assert client.get("/ops/v1/monitoring/mcp-tools/refreshes/any-token").status_code == 503

    bare = _bare_monitoring_client(monkeypatch)
    assert bare.get("/ops/v1/monitoring/mcp-tools/refreshes/any-token").status_code == 503


def test_mcp_tool_refresh_status_rejects_malformed_signed_tokens(monitoring_client):
    client, _ = monitoring_client

    reversed_range = _tool_token(start="2026-11-18", end="2026-11-17")
    assert client.get(f"/ops/v1/monitoring/mcp-tools/refreshes/{reversed_range}").status_code == 404

    not_a_mapping = _tool_token(revisions=["2026-11-17"])
    assert client.get(f"/ops/v1/monitoring/mcp-tools/refreshes/{not_a_mapping}").status_code == 404


def test_mcp_tool_refresh_status_reports_uncovered_and_timed_out(monitoring_client):
    client, store = monitoring_client
    day = date(2026, 11, 17)

    store.states.return_value = []
    encoded_revision = urlsafe_b64encode(pack("!1Q", 5)).decode("ascii")
    uncovered = _tool_token(revision_bytes=encoded_revision)
    response = client.get(f"/ops/v1/monitoring/mcp-tools/refreshes/{uncovered}")
    assert response.json()["data"] == {"status": "uncovered", "data_as_of": None}

    stale = datetime.now(timezone.utc) - timedelta(seconds=30)
    waiting = _tool_token(revision_bytes=encoded_revision, requested=stale.timestamp())
    store.states.return_value = [{"statistic_date": day, "published_source_revision": None,
                                  "source_snapshot_at": datetime(2026, 11, 17, tzinfo=timezone.utc)}]
    response = client.get(f"/ops/v1/monitoring/mcp-tools/refreshes/{waiting}")
    assert response.json()["data"]["status"] == "timed_out"
    assert response.json()["data"]["data_as_of"] == "2026-11-17T00:00:00+00:00"


def test_mcp_tool_refresh_status_still_resolves_map_based_tokens(monitoring_client):
    client, store = monitoring_client
    day = date(2026, 11, 17)
    store.states.return_value = [{"statistic_date": day, "published_source_revision": 3, "source_snapshot_at": None}]
    token = _tool_token(revisions={day.isoformat(): 3})
    assert client.get(f"/ops/v1/monitoring/mcp-tools/refreshes/{token}").json()["data"]["status"] == "completed"


def test_mcp_tool_refresh_status_reports_store_failure_as_temporarily_unavailable(monitoring_client):
    client, store = monitoring_client
    store.states.side_effect = RuntimeError("store down")
    token = _tool_token()
    response = client.get(f"/ops/v1/monitoring/mcp-tools/refreshes/{token}")
    assert response.status_code == 503
    assert response.json()["message"] == "MCP tool monitoring refresh is temporarily unavailable"
