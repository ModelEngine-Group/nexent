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
