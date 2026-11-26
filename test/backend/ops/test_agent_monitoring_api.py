# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Agent summary coverage, request validation and dependency failures."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI

from management.services.permission.identity.session import authenticate
from ops.api import monitoring
from ops.monitoring.query import read_agents, read_models
from permissions import rbac
from permissions.models import CurrentUser


DAY = date(2026, 11, 18)
MIDNIGHT = datetime.combine(DAY, datetime.min.time(), timezone.utc)
PATH = "/ops/v1/monitoring/agents/summary"


@pytest.mark.parametrize(
    ("published", "coverage_start", "up_to_date", "label", "metrics"),
    [
        (True, MIDNIGHT, True, "covered", (0, None, 0)),
        (True, MIDNIGHT, False, "covered", (0, None, 0)),
        (True, MIDNIGHT + timedelta(hours=1), True, "partial", (None, None, None)),
        (False, None, False, "uncovered", (None, None, None)),
    ],
)
def test_agent_summary_distinguishes_zero_from_unavailable(
    published, coverage_start, up_to_date, label, metrics,
):
    state = {"tenant_id": "tenant", "statistic_date": DAY, "publish_id": "ready" if published else None,
             "source_snapshot_at": MIDNIGHT if published else None, "source_revision": 4,
             "published_source_revision": (4 if up_to_date else 3) if published else None}
    store = Mock()
    store.has_failed_batches.return_value = False
    store.coverage_starts.return_value = {"tenant": coverage_start}
    point = Mock()
    point.documents.return_value = []

    @contextmanager
    def snapshot(*_):
        yield [state], point if published else None

    service = SimpleNamespace(store=store, zone=ZoneInfo("UTC"), publication_snapshot=snapshot)
    data, status = read_agents(service, tenant="tenant", start=DAY, end=DAY, groups=[12, 13], agent_id=21)

    assert (data["execution_count"], data["avg_duration_ms"], data["duration_sample_count"]) == metrics
    assert data["succeeded_count"] == data["failed_count"] == metrics[0]
    assert data["success_rate"] is None
    assert status == {"coverage_state": label, "data_as_of": state["source_snapshot_at"], "is_stale": not up_to_date}
    if published:
        clause = point.documents.call_args.args[0]["bool"]["filter"]
        assert {"terms": {"initiator_group_ids": [12, 13]}} in clause
        assert {"term": {"agent_id": 21}} in clause


def test_model_reader_preserves_its_existing_filters_and_catalog(monkeypatch):
    state = {"tenant_id": "tenant", "statistic_date": DAY, "publish_id": "ready",
             "source_snapshot_at": MIDNIGHT, "source_revision": 4, "published_source_revision": 4}
    point = Mock()
    point.documents.return_value = [{"request_count": 2}]
    store = Mock()
    store.has_failed_batches.return_value = False
    store.coverage_starts.return_value = {"tenant": MIDNIGHT}
    models = [{"tenant_id": "tenant", "model_id": 7, "model_type": "llm"},
              {"tenant_id": "tenant", "model_id": 8, "model_type": "vlm"}]
    monkeypatch.setattr("ops.monitoring.query.model_catalog", lambda _: models)

    @contextmanager
    def snapshot(tenant, kind, start, end):
        assert (tenant, kind, start, end) == ("tenant", "model", DAY, DAY)
        yield [state], point

    service = SimpleNamespace(store=store, zone=ZoneInfo("UTC"), publication_snapshot=snapshot)
    rows, catalog, dates, status = read_models(
        service, tenant="tenant", start=DAY, end=DAY, groups=[12], model_id=7, model_type="llm",
    )
    assert (rows, catalog, dates) == ([{"request_count": 2}], models[:1], [DAY])
    assert status == {"coverage_state": "covered", "data_as_of": MIDNIGHT, "is_stale": False}
    clauses = point.documents.call_args.args[0]["bool"]["filter"]
    assert clauses[:4] == [
        {"term": {"fact_kind": "model"}}, {"terms": {"initiator_group_ids": [12]}},
        {"term": {"model_id": 7}}, {"term": {"model_type": "llm"}},
    ]


@pytest.fixture
def agent_app(monkeypatch):
    app = FastAPI()
    app.include_router(monitoring.ops_router)
    app.dependency_overrides[authenticate] = lambda: CurrentUser("operator", "tenant", "OPS")
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}})
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"start_date": "2026-11-19"},
    {"start_date": "2025-11-17"},
    {"agent_id": 0},
    {"group_ids": [12, -1]},
    {"group_ids": 2**31},
    {"group_ids": [12] * 101},
    {"tenant_id": ""},
])
async def test_agent_summary_rejects_invalid_filters(agent_app, overrides):
    params = {"start_date": "2026-11-18", "end_date": "2026-11-18", **overrides}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_app), base_url="http://ops") as client:
        response = await client.get(PATH, params=params)
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [False, True])
async def test_agent_summary_reports_unavailable_dependencies(agent_app, monkeypatch, configured):
    if configured:
        agent_app.state.monitoring = object()
        monkeypatch.setattr(monitoring, "read_agents", Mock(side_effect=RuntimeError("private storage details")))
    params = {"start_date": "2026-11-18", "end_date": "2026-11-18"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_app), base_url="http://ops") as client:
        response = await client.get(PATH, params=params)
    assert response.status_code == 503
    assert "private storage details" not in response.text
