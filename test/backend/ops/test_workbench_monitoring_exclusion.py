# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""System identity filtering with real catalog SQL and published read projections."""

from contextlib import contextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from infrastructure.rdb import agent_monitoring
from management.db.agent.models import AgentInfo
from management.services.permission.identity.session import authenticate
from ops.api import monitoring
from ops.api.monitoring import _agent_items
from ops.monitoring import agent_tokens, query
from permissions import rbac
from permissions.models import CurrentUser
from test.backend.ops.test_agent_tokens import model_day


DAY = date(2026, 11, 24)
PREVIOUS = date(2026, 11, 23)
MIDNIGHT = datetime(2026, 11, 23, tzinfo=timezone.utc)


@pytest.fixture
def catalog(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    schema = AgentInfo.__table__.schema
    engine = engine.execution_options(schema_translate_map={schema: None})
    table = Table(AgentInfo.__tablename__, MetaData(),
                  *(Column(name, Integer) for name in ("agent_id", "version_no", "current_version_no")),
                  *(Column(name, String) for name in
                    ("tenant_id", "name", "display_name", "model_ids", "group_ids", "delete_flag", "system_key")),
                  schema=schema)
    table.create(engine)
    rows = [
        (97, 0, "asset-owner", "Renamed scheduler", "workbench_main", "N"),
        (97, 1, "asset-owner", "Old release", "workbench_main", "N"),
        (98, 1, "asset-owner", "Deleted release", "workbench_main", "Y"),
        (50, 0, "a", "workbench_main", None, "N"),
        (101, 0, "a", "Nexent Workbench", "other_system", "N"),
    ]
    with engine.begin() as conn:
        conn.execute(table.insert(), [dict(agent_id=i, version_no=v, current_version_no=1,
                     tenant_id=t, name=n, display_name=n, system_key=k, delete_flag=d,
                     model_ids="", group_ids="12") for i, v, t, n, k, d in rows])
    with Session(engine) as session:
        @contextmanager
        def database():
            yield session
        monkeypatch.setattr(query, "get_db_session", database)
        monkeypatch.setattr(agent_monitoring, "get_db_session", database)
        yield session, table
    engine.dispose()


@pytest.fixture
def publication(catalog):
    states = [dict(tenant_id="a", statistic_date=day, publish_id="published", source_revision=1,
                   published_source_revision=1, source_snapshot_at=MIDNIGHT) for day in (PREVIOUS, DAY)]
    rows = [dict(tenant_id="a", agent_id=i, statistic_date=day.isoformat(), execution_count=count,
                 duration_sum_ms=count * 100, duration_sample_count=count,
                 succeeded_count=count, failed_count=0, parent_agent_run_id="scheduler-run",
                 root_agent_run_id="scheduler-run")
            for day in (PREVIOUS, DAY) for i, count in ((97, 900), (98, 100), (50, 2), (101, 1))]
    token_rows = [model_day(i, f"run-{i}-{day}", day, dict(input_tokens=10, output_tokens=2, total_tokens=12))
                  for day in (PREVIOUS, DAY) for i in (97, 98, 50, 101)]
    def documents(constraints):
        clauses = constraints["bool"]["filter"]
        selected = token_rows if {"term": {"fact_kind": "model"}} in clauses else rows
        ids = [clause["term"]["agent_id"] for clause in clauses if "agent_id" in clause.get("term", {})]
        return [row for row in selected if not ids or row["agent_id"] == ids[0]]
    point = SimpleNamespace(documents=documents)
    @contextmanager
    def snapshot(*_):
        yield states, point
    store = Mock()
    store.has_failed_batches.return_value = False
    store.coverage_starts.return_value = {"a": MIDNIGHT}
    store.failed_batch_tenants.return_value = set()
    return SimpleNamespace(store=store, zone=ZoneInfo("UTC"), publication_snapshot=snapshot), rows, token_rows


def test_identity_not_local_id_name_owner_or_release_controls_exclusion(catalog):
    assert agent_monitoring.excluded_monitoring_agent_ids() == {97, 98}
    assert {row["agent_id"] for row in query.agent_catalog(None, None)} == {50, 101}
    assert query.agent_catalog("asset-owner", 97) == []
    assert query.agent_catalog_tenants(None) == {"a"}


def test_summary_views_rankings_and_cross_day_trends_keep_dispatched_agents(publication):
    service, raw, _ = publication
    scope = dict(tenant="a", start=PREVIOUS, end=DAY, groups=[12], agent_id=None)
    summary, _ = query.read_agents(service, **scope)
    assert summary["execution_count"] == 6
    assert summary["avg_duration_ms"] == 100 and summary["success_rate"] == 1
    items, count, history, _ = query.read_agent_views(service, **scope)
    assert count == 2 and {row["agent_id"] for row in items} == {50, 101}
    assert [day["execution_count"] for day in history] == [3, 3]
    assert [row["agent_id"] for row in _agent_items(items, "execution_count")[:5]] == [50, 101]
    assert len(raw) == 8 and {row["agent_id"] for row in raw} == {50, 97, 98, 101}
    excluded_scope = {**scope, "agent_id": 97}
    excluded_items, excluded_count, _, _ = query.read_agent_views(service, **excluded_scope)
    assert excluded_items == [] and excluded_count == 0
    assert query.read_agents(service, **excluded_scope)[0]["execution_count"] == 0


def test_agent_token_projection_excludes_only_scheduler_usage_and_keeps_model_data(publication):
    service, _, raw = publication
    result = agent_tokens.read_agent_tokens(service, tenant="a", start=PREVIOUS, end=DAY,
                                            groups=[12], agent_id=None)
    assert result.tokens["total_tokens"]["value"] == "48"
    assert set(result.agents) == {("a", 50), ("a", 101)}
    assert [day["tokens"]["total_tokens"]["value"] for day in result.days.values()] == ["24", "24"]
    model_rows, _, _ = query._read_published_rows(service, tenant="a", kind="model", start=PREVIOUS, end=DAY)
    assert len(model_rows) == len(raw) == 8


def test_exclusion_database_failure_is_not_silently_ignored(publication, monkeypatch):
    def fail():
        raise RuntimeError("catalog unavailable")
    monkeypatch.setattr(query, "excluded_monitoring_agent_ids", fail)
    with pytest.raises(RuntimeError, match="catalog unavailable"):
        query.read_agents(publication[0], tenant="a", start=PREVIOUS, end=DAY, groups=[], agent_id=None)


@pytest.mark.asyncio
async def test_http_projections_use_the_same_exclusion(publication, monkeypatch):
    app = FastAPI()
    app.include_router(monitoring.ops_router)
    app.state.monitoring = publication[0]
    app.dependency_overrides[authenticate] = lambda: CurrentUser("operator", "a", "OPS")
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}})
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    params = {"start_date": PREVIOUS.isoformat(), "end_date": DAY.isoformat(), "group_ids": 12}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops") as client:
        summary = await client.get("/ops/v1/monitoring/agents/summary", params=params)
        assert summary.status_code == 200
        assert summary.json()["data"]["execution_count"] == 6
        assert summary.json()["tokens"]["total_tokens"]["value"] == "48"
        listing = await client.get("/ops/v1/monitoring/agents", params=params)
        assert listing.status_code == 200
        assert listing.json()["data"]["current_agent_count"] == 2
        assert {row["agent_id"] for row in listing.json()["data"]["items"]} == {50, 101}
        trends = await client.get("/ops/v1/monitoring/agents/trends", params=params)
        assert trends.status_code == 200
        assert [day["execution_count"] for day in trends.json()["data"]] == [3, 3]
        for metric in ("execution_count", "total_tokens", "success_rate"):
            ranking = await client.get("/ops/v1/monitoring/agents/rankings", params={**params, "metric": metric})
            assert ranking.status_code == 200
            assert {row["agent_id"] for row in ranking.json()["data"]} == {50, 101}
