# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Regression tests for reporting model monitoring coverage and refresh status."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import jwt
import pytest
from fastapi.testclient import TestClient

from management.services.permission.identity.session import authenticate
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


def test_skill_routes_filter_sort_and_report_trend_coverage(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    status = {"coverage_state": "covered", "is_stale": False, "data_as_of": "2026-11-23T00:00:00Z"}
    rows = [
        {"tenant_id": "tenant", "skill_id": "1", "skill_name": "Alpha", "statistic_date": "2026-11-23",
         "usage_count": 2},
        {"tenant_id": "tenant", "skill_id": "2", "skill_name": "Beta", "statistic_date": "2026-11-23",
         "usage_count": 5},
    ]
    catalog = [{"tenant_id": "tenant", "skill_id": "1", "skill_name": "Alpha"},
               {"tenant_id": "tenant", "skill_id": "2", "skill_name": "Beta"}]
    monkeypatch.setattr(monitoring, "read_skills", lambda *_args, **_kwargs: (rows, catalog, [date(2026, 11, 23)], status))

    listing = client.get("/ops/v1/monitoring/skills", params={
        "start_date": "2026-11-23", "end_date": "2026-11-23", "search": "beta", "page_size": 1,
    })
    assert listing.status_code == 200
    assert listing.json()["data"] == {"items": [{**catalog[1], "metrics": {"usage_count": 5}}], "total": 1}
    assert client.get("/ops/v1/monitoring/skills/summary",
                      params={"start_date": "2026-11-23", "end_date": "2026-11-23"}).json()["data"] == {
                          "current_skill_count": 2, "usage_count": 7, "skill_count": 2}
    assert [item["skill_id"] for item in client.get(
        "/ops/v1/monitoring/skills/rankings",
        params={"start_date": "2026-11-23", "end_date": "2026-11-23"},
    ).json()["data"]] == ["2", "1"]
    trend = client.get("/ops/v1/monitoring/skills/trends",
                       params={"start_date": "2026-11-22", "end_date": "2026-11-23"})
    assert trend.json()["data"] == [{"statistic_date": "2026-11-22", "usage_count": None},
                                     {"statistic_date": "2026-11-23", "usage_count": 7}]


def test_skill_query_returns_service_unavailable_on_missing_or_failed_service(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    app = client.app
    original = app.state.monitoring
    app.state.monitoring = None
    try:
        response = client.get("/ops/v1/monitoring/skills",
                              params={"start_date": "2026-11-23", "end_date": "2026-11-23"})
        assert response.status_code == 503
    finally:
        app.state.monitoring = original
    monkeypatch.setattr(monitoring, "read_skills", Mock(side_effect=RuntimeError("offline")))
    response = client.get("/ops/v1/monitoring/skills",
                          params={"start_date": "2026-11-23", "end_date": "2026-11-23"})
    assert response.status_code == 503


def test_skill_refresh_rejects_uncovered_dates_and_reports_completion(monitoring_client):
    client, store = monitoring_client
    day = date(2026, 11, 23)
    store.states.return_value = [{"statistic_date": day, "source_revision": 4,
                                  "published_source_revision": 4, "source_snapshot_at": "snapshot"}]
    response = client.post("/ops/v1/monitoring/skills/refresh", json={
        "tenant_id": "tenant", "start_date": day.isoformat(), "end_date": day.isoformat(),
    })
    assert response.status_code == 202
    refresh_id = response.json()["data"]["refresh_id"]
    status = client.get(f"/ops/v1/monitoring/skills/refreshes/{refresh_id}")
    assert status.json()["data"] == {"status": "completed", "data_as_of": "snapshot"}

    store.states.return_value = []
    response = client.post("/ops/v1/monitoring/skills/refresh", json={
        "tenant_id": "tenant", "start_date": day.isoformat(), "end_date": day.isoformat(),
    })
    assert response.status_code == 409
    assert response.json()["message"]["code"] == "MONITORING_DATES_UNCOVERED"


def test_skill_refresh_status_rejects_invalid_token_and_backend_failure(monitoring_client, monkeypatch):
    client, store = monitoring_client
    app = client.app
    original = app.state.monitoring
    app.state.monitoring = None
    try:
        assert client.get("/ops/v1/monitoring/skills/refreshes/not-a-token").status_code == 503
    finally:
        app.state.monitoring = original
    assert client.get("/ops/v1/monitoring/skills/refreshes/not-a-token").status_code == 404
    store.states.side_effect = RuntimeError("offline")
    now = datetime.now(timezone.utc)
    token = jwt.encode({"aud": "ops-skill-monitoring-refresh", "tenant": "tenant", "revisions": {},
                        "start": "2026-11-23", "end": "2026-11-23", "requested": now.timestamp(),
                        "exp": now + timedelta(minutes=1)}, monitoring._refresh_key("skill"), algorithm="HS256")
    assert client.get(f"/ops/v1/monitoring/skills/refreshes/{token}").status_code == 503


def test_skill_refresh_rejects_missing_tenant_or_unavailable_secret(monitoring_client, monkeypatch):
    client, _ = monitoring_client
    monkeypatch.setattr(monitoring, "operations_scope", lambda *_args: None)
    response = client.post("/ops/v1/monitoring/skills/refresh", json={
        "tenant_id": "tenant", "start_date": "2026-11-23", "end_date": "2026-11-23",
    })
    assert response.status_code == 422
    monkeypatch.setattr(monitoring, "operations_scope", lambda user, tenant, *_: tenant or user.tenant_id)
    monkeypatch.setattr(monitoring, "JWT_SECRET", "")
    response = client.post("/ops/v1/monitoring/skills/refresh", json={
        "tenant_id": "tenant", "start_date": "2026-11-23", "end_date": "2026-11-23",
    })
    assert response.status_code == 503


def test_skill_refresh_reports_store_failure_and_signed_token_errors(monitoring_client, monkeypatch):
    client, store = monitoring_client
    store.states.side_effect = RuntimeError("offline")
    response = client.post("/ops/v1/monitoring/skills/refresh", json={
        "tenant_id": "tenant", "start_date": "2026-11-23", "end_date": "2026-11-23",
    })
    assert response.status_code == 503

    store.states.side_effect = None
    now = datetime.now(timezone.utc)
    for claims in (
            {"start": "2026-11-23", "end": "2027-11-24", "revisions": {}},
        {"start": "2026-11-23", "end": "2026-11-23", "revisions": []},
    ):
        token = jwt.encode({"aud": "ops-skill-monitoring-refresh", "tenant": "tenant", **claims,
                            "requested": now.timestamp(), "exp": now + timedelta(minutes=1)},
                           monitoring._refresh_key("skill"), algorithm="HS256")
        assert client.get(f"/ops/v1/monitoring/skills/refreshes/{token}").status_code == 404


@pytest.mark.parametrize("requested, expected", [
    (0, "timed_out"), (datetime.now(timezone.utc).timestamp(), "running"), (0, "uncovered"),
])
def test_skill_refresh_reports_uncovered_or_pending_publication(monitoring_client, requested, expected):
    client, store = monitoring_client
    day = date(2026, 11, 23)
    store.states.return_value = [] if expected == "uncovered" else [
        {"statistic_date": day, "published_source_revision": 1, "source_snapshot_at": None}
    ]
    if expected == "timed_out":
        store.states.return_value = [{"statistic_date": day, "published_source_revision": 1,
                                      "source_snapshot_at": None}]
    token = jwt.encode({"aud": "ops-skill-monitoring-refresh", "tenant": "tenant", "revisions": {day.isoformat(): 2},
                        "start": day.isoformat(), "end": day.isoformat(), "requested": requested,
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=1)},
                       monitoring._refresh_key("skill"), algorithm="HS256")
    assert client.get(f"/ops/v1/monitoring/skills/refreshes/{token}").json()["data"]["status"] == expected
