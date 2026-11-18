# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Regression tests for reporting model monitoring coverage and refresh status."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import jwt
import pytest
from fastapi.testclient import TestClient

from gateway.authentication.auth import authenticate
from ops.api import application, monitoring
from permissions.models import CurrentUser


@pytest.fixture
def monitoring_client(monkeypatch):
    monkeypatch.setattr(application, "OPS_MONITORING_ENABLED", True)
    app = application.create_app()
    store = Mock()
    store.states.return_value = []
    app.state.monitoring = SimpleNamespace(store=store, zone=ZoneInfo("UTC"))
    app.dependency_overrides[authenticate] = lambda: CurrentUser("operator", "tenant", "OPS")
    monkeypatch.setattr(monitoring, "operations_scope", lambda user, tenant, *_: tenant or user.tenant_id)
    monkeypatch.setattr(monitoring, "JWT_SECRET", "isolated-monitoring-jwt-secret-for-tests")
    with TestClient(app) as client:
        yield client, store


def test_refresh_conflicts_when_any_requested_day_has_no_source(monitoring_client):
    client, store = monitoring_client
    store.states.return_value = [{"statistic_date": date(2026, 11, 17), "source_revision": 0}]
    scope = {"start_date": "2026-11-16", "end_date": "2026-11-17"}
    response = client.post("/ops/v1/monitoring/models/refresh", json=scope)
    assert response.status_code == 409
    assert response.json()["message"] == {"code": "MONITORING_DATES_UNCOVERED", "missing_dates": ["2026-11-16"]}


def test_empty_targets_in_existing_refresh_token_do_not_complete(monitoring_client):
    client, _ = monitoring_client
    now = datetime.now(timezone.utc)
    token = jwt.encode({"aud": "ops-model-monitoring-refresh", "tenant": "tenant", "revisions": {},
                        "start": "2026-11-17", "end": "2026-11-17", "requested": now.timestamp(),
                        "exp": now + timedelta(minutes=1)}, monitoring._refresh_key(), algorithm="HS256")
    response = client.get(f"/ops/v1/monitoring/models/refreshes/{token}")
    assert response.status_code == 200
    assert response.json()["data"] == {"status": "uncovered", "data_as_of": None}


def test_refresh_waits_for_its_target_version(monitoring_client):
    client, store = monitoring_client
    day = date(2026, 11, 17)
    store.states.return_value = [{"statistic_date": day, "source_revision": 2, "published_source_revision": 1,
                                 "source_snapshot_at": None}]
    scope = {"start_date": day.isoformat(), "end_date": day.isoformat()}
    response = client.post("/ops/v1/monitoring/models/refresh", json=scope)
    assert response.status_code == 202
    path = f"/ops/v1/monitoring/models/refreshes/{response.json()['data']['refresh_id']}"
    assert client.get(path).json()["data"]["status"] == "running"
    store.states.return_value[0]["published_source_revision"] = 2
    assert client.get(path).json()["data"]["status"] == "completed"


def test_year_long_refresh_stays_bounded_and_keeps_each_days_target(monitoring_client):
    client, store = monitoring_client
    start = date(2025, 11, 17)
    days = [start + timedelta(days=offset) for offset in range(366)]
    rows = []
    for offset, day in enumerate(days):
        revision = 2**63 - 1 - offset
        rows.append({"statistic_date": day, "source_revision": revision, "published_source_revision": revision,
                     "source_snapshot_at": None})
    rows[-1]["published_source_revision"] -= 1
    store.states.return_value = list(reversed(rows))
    scope = {"start_date": days[0].isoformat(), "end_date": days[-1].isoformat()}

    response = client.post("/ops/v1/monitoring/models/refresh", json=scope)
    assert response.status_code == 202
    path = f"/ops/v1/monitoring/models/refreshes/{response.json()['data']['refresh_id']}"
    assert len(path) < 6144
    assert client.get(path).json()["data"]["status"] == "running"
    rows[-1]["published_source_revision"] = rows[-1]["source_revision"]
    assert client.get(path).json()["data"]["status"] == "completed"


def test_existing_map_based_refresh_token_still_resolves(monitoring_client):
    client, store = monitoring_client
    day = date(2026, 11, 17)
    store.states.return_value = [{"statistic_date": day, "published_source_revision": 3, "source_snapshot_at": None}]
    now = datetime.now(timezone.utc)
    token = jwt.encode({"aud": "ops-model-monitoring-refresh", "tenant": "tenant", "revisions": {day.isoformat(): 3},
                        "start": day.isoformat(), "end": day.isoformat(), "requested": now.timestamp(),
                        "exp": now + timedelta(minutes=1)}, monitoring._refresh_key(), algorithm="HS256")
    assert client.get(f"/ops/v1/monitoring/models/refreshes/{token}").json()["data"]["status"] == "completed"


def test_trend_keeps_missing_dates_separate_from_published_zero_days(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    monkeypatch.setattr(monitoring, "read_models", lambda *_args, **_kwargs: ([], [], [date(2026, 11, 17)],
                        {"coverage_state": "partial", "is_stale": False, "data_as_of": None}))
    response = client.get("/ops/v1/monitoring/models/trends",
                          params={"start_date": "2026-11-16", "end_date": "2026-11-17"})
    assert response.status_code == 200
    missing, covered = response.json()["data"]
    assert missing["statistic_date"] == "2026-11-16"
    assert all(value is None for key, value in missing.items() if key != "statistic_date")
    assert covered["statistic_date"] == "2026-11-17"
    assert covered["request_count"] == 0
    assert covered["total_tokens"]["value"] == "0"


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
                        lambda *_args, **_kwargs: (_tool_rows(), [date(2026, 11, 17)], _tool_status()))

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
                        lambda *_args, **_kwargs: ([], [], _tool_status(coverage_state="uncovered")))

    uncovered = client.get("/ops/v1/monitoring/mcp-tools/summary", params=params)
    assert uncovered.json()["data"] == {"service_count": 0, "active_services": 0, "tool_count": 0,
                                       "active_tools": 0, "request_count": None, "error_count": None,
                                       "error_eligible_count": None, "error_rate": None, "avg_duration_ms": None}

    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: (_tool_rows(), [date(2026, 11, 17)], _tool_status()))
    covered = client.get("/ops/v1/monitoring/mcp-tools/summary", params=params)
    assert covered.json()["data"]["tool_count"] == 2
    assert covered.json()["data"]["request_count"] == 3
    assert covered.json()["data"]["error_rate"] == 1 / 3
    assert covered.json()["data"]["avg_duration_ms"] == 70 / 3


def test_mcp_tools_trends_keep_missing_dates_separate_from_zero_days(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    monkeypatch.setattr(monitoring, "read_mcp_tools",
                        lambda *_args, **_kwargs: (_tool_rows()[:1], [date(2026, 11, 17)], _tool_status()))

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
                        lambda *_args, **_kwargs: (rows, [date(2026, 11, 17)], _tool_status()))

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
                        lambda *_args, **_kwargs: (rows, [date(2026, 11, 17)], _tool_status()))

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
                        lambda *_args, **_kwargs: (rows, [date(2026, 11, 17)], _tool_status()))

    response = client.get("/ops/v1/monitoring/mcp-tools/summary",
                          params={"start_date": "2026-11-17", "end_date": "2026-11-17"})
    data = response.json()["data"]
    assert data["service_count"] == 1
    assert data["active_services"] == 1
    assert data["tool_count"] == 2
    assert data["active_tools"] == 2
    assert data["request_count"] == 3


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
                        lambda *_args, **_kwargs: (rows, [date(2026, 11, 17)], _tool_status()))

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
        return ([], [], _tool_status())

    monkeypatch.setattr(monitoring, "read_mcp_tools", fake_read)
    client.get("/ops/v1/monitoring/mcp-tools",
               params={"start_date": "2026-11-17", "end_date": "2026-11-17",
                       "dimension": "tools", "tool_name": "search_docs"})
    assert captured["tool_name"] == "search_docs"


def test_mcp_tools_catalog_scopes_to_the_requested_tenant(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    monkeypatch.setattr(monitoring, "mcp_server_catalog",
                        lambda tenant: [{"service_id": 3, "name": "docs", "type": "container"}]
                        if tenant == "tenant" else [])

    response = client.get("/ops/v1/monitoring/mcp-tools/catalog")
    assert response.status_code == 200
    assert response.json()["data"] == [{"service_id": 3, "name": "docs", "type": "container"}]

    other = client.get("/ops/v1/monitoring/mcp-tools/catalog", params={"tenant_id": "elsewhere"})
    assert other.json()["data"] == []


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
                [date(2026, 11, 17)], _tool_status())

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
