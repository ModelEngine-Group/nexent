# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current Agent metadata and published directory, trend and ranking contracts."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.dialects import postgresql

from gateway.authentication.auth import authenticate
from ops.api import monitoring
from ops.monitoring.agent_tokens import AgentTokenUsage
from ops.monitoring import query
from permissions import rbac
from permissions.models import CurrentUser


DAY = date(2026, 11, 19)
PREVIOUS = DAY - timedelta(days=1)
MIDNIGHT = datetime.combine(PREVIOUS, datetime.min.time(), timezone.utc)
BASE = "/ops/v1/monitoring/agents"


def test_current_catalog_uses_active_drafts_and_authorized_ids(monkeypatch):
    session = Mock()
    session.execute.return_value.mappings.return_value = [
        {"tenant_id": "a", "agent_id": 21, "group_ids": "12,13", "name": "root"},
    ]

    @contextmanager
    def database():
        yield session

    monkeypatch.setattr(query, "get_db_session", database)
    assert query.agent_catalog("a", 21) == [
        {"tenant_id": "a", "agent_id": 21, "configured_group_ids": [12, 13], "name": "root"},
    ]
    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    for predicate in ("delete_flag = 'N'", "version_no = 0", "tenant_id = 'a'", "agent_id = 21"):
        assert predicate in sql
    assert "prompt" not in sql and "verification_config" not in sql


@pytest.fixture
def publication(monkeypatch):
    inventory = [{"tenant_id": "a", "agent_id": number, "name": f"agent-{number}"} for number in (21, 22, 23)]
    inventory.append({"tenant_id": "b", "agent_id": 21, "name": "other"})
    rows = [
        {"tenant_id": "a", "agent_id": 21, "statistic_date": PREVIOUS.isoformat(),
         "execution_count": 1, "duration_sum_ms": 100, "duration_sample_count": 1},
        {"tenant_id": "a", "agent_id": 21, "statistic_date": DAY.isoformat(),
         "execution_count": 3, "duration_sum_ms": 900, "duration_sample_count": 3},
        {"tenant_id": "a", "agent_id": 99, "statistic_date": DAY.isoformat(),
         "execution_count": 2**53 + 1, "duration_sum_ms": 0, "duration_sample_count": 0},
    ]
    states = [{"tenant_id": "a", "statistic_date": day, "publish_id": "published",
               "source_snapshot_at": MIDNIGHT, "source_revision": 3, "published_source_revision": 3}
              for day in (PREVIOUS, DAY)]
    store = Mock()
    store.has_failed_batches.return_value = False
    store.coverage_starts.return_value = {"a": MIDNIGHT}
    service = SimpleNamespace(store=store, zone=ZoneInfo("UTC"))
    monkeypatch.setattr(query, "agent_catalog", lambda *_: inventory)
    monkeypatch.setattr(query, "_read_published_rows", lambda *_, **__: (rows, states, states))
    return service, rows, states


def test_views_keep_tenant_identity_exact_counts_and_weighted_durations(publication):
    service, _, _ = publication
    items, current, history, status = query.read_agent_views(
        service, tenant=None, start=PREVIOUS, end=DAY, groups=[12, 13], agent_id=None,
    )
    lookup = {(row["tenant_id"], row["agent_id"]): row for row in items}
    assert current == 4 and len(items) == 5
    assert lookup["a", 21]["metrics"] == {
        "execution_count": 4, "avg_duration_ms": 250, "duration_sample_count": 4,
        "succeeded_count": None, "failed_count": None, "success_rate": None,
    }
    assert lookup["a", 22]["metrics"] == {
        "execution_count": 0, "avg_duration_ms": None, "duration_sample_count": 0,
        "succeeded_count": 0, "failed_count": 0, "success_rate": None,
    }
    assert lookup["b", 21]["metrics"] is None
    assert lookup["a", 99]["metrics"]["execution_count"] == 2**53 + 1
    assert lookup["a", 99]["is_current"] is False
    assert [row["coverage_state"] for row in history] == ["partial", "partial"]
    assert [row["execution_count"] for row in history] == [1, 2**53 + 4]
    assert status["coverage_state"] == "partial" and not status["is_stale"]
    service.store.coverage_starts.assert_called_once()


def test_trends_fill_known_zero_uncovered_and_stale(publication):
    service, rows, states = publication
    rows.clear()
    service.store.has_failed_batches.return_value = True
    states[0]["published_source_revision"] = 2
    items, _, history, status = query.read_agent_views(
        service, tenant=None, start=PREVIOUS - timedelta(days=1), end=DAY, groups=[], agent_id=None,
    )
    assert history[0] == {"statistic_date": PREVIOUS - timedelta(days=1), "execution_count": None,
                          "avg_duration_ms": None, "duration_sample_count": None, "coverage_state": "uncovered",
                          "succeeded_count": None, "failed_count": None, "success_rate": None}
    # The controlled catalog also contains an uncovered tenant, so these global days remain partial.
    assert history[1]["execution_count"] is None and history[1]["coverage_state"] == "partial"
    assert status["is_stale"] and status["coverage_state"] == "partial"
    assert all(row["metrics"] is None for row in items)


def test_single_tenant_complete_dates_report_zero(publication, monkeypatch):
    service, rows, _ = publication
    rows.clear()
    monkeypatch.setattr(query, "agent_catalog", lambda *_: [{"tenant_id": "a", "agent_id": 21}])
    _, _, history, status = query.read_agent_views(
        service, tenant="a", start=PREVIOUS, end=DAY, groups=[555], agent_id=21,
    )
    assert status["coverage_state"] == "covered"
    assert all(row["execution_count"] == 0 and row["coverage_state"] == "covered" for row in history)
    assert all(row["succeeded_count"] == row["failed_count"] == 0 and row["success_rate"] is None for row in history)


def test_views_and_daily_trends_merge_result_counts_before_division(publication):
    service, rows, _ = publication
    rows[0].update(succeeded_count=1, failed_count=0)
    rows[1].update(execution_count=4, succeeded_count=1, failed_count=3)
    rows[2].update(succeeded_count=0, failed_count=0)
    items, _, history, _ = query.read_agent_views(
        service, tenant=None, start=PREVIOUS, end=DAY, groups=[12, 13], agent_id=None,
    )
    result, = [item["metrics"] for item in items if (item["tenant_id"], item["agent_id"]) == ("a", 21)]
    assert (result["succeeded_count"], result["failed_count"], result["success_rate"]) == (2, 3, 0.4)
    assert [row["success_rate"] for row in history] == [1, 0.25]


@pytest.fixture
def view_app(monkeypatch):
    app = FastAPI()
    app.include_router(monitoring.ops_router)
    app.state.monitoring = object()
    app.dependency_overrides[authenticate] = lambda: CurrentUser("operator", "a", "OPS")
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}, "SU": {"ops.dashboard:read"}})
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    items = [{"tenant_id": "a", "agent_id": number, "name": f"internal-{number}", "display_name": "Visible",
              "metrics": {"execution_count": number // 2, "avg_duration_ms": number * 10}}
             for number in range(1, 9)]
    items += [{"tenant_id": "a", "agent_id": 9, "name": "unknown", "metrics": None}]
    reader = Mock(return_value=(items, 9, [], {"coverage_state": "covered", "is_stale": False, "data_as_of": None}))
    monkeypatch.setattr(monitoring, "read_agent_views", reader)
    monkeypatch.setattr(monitoring, "read_agent_tokens", Mock(return_value=AgentTokenUsage({}, {}, {}, {})))
    return app, reader


async def get(app, suffix="", **params):
    selection = {"start_date": DAY.isoformat(), "end_date": DAY.isoformat(), **params}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops") as client:
        return await client.get(BASE + suffix, params=selection)


@pytest.mark.asyncio
async def test_directory_searches_both_names_and_pages_after_stable_sort(view_app):
    app, reader = view_app
    body = (await get(app, search="VISIBLE", page=2, page_size=2)).json()
    assert [row["agent_id"] for row in body["data"]["items"]] == [7, 4]
    assert body["data"]["total"] == 8 and body["data"]["current_agent_count"] == 9
    by_name = (await get(app, search="INTERNAL-2")).json()["data"]["items"]
    assert [row["agent_id"] for row in by_name] == [2]
    ascending = (await get(app, sort_by="avg_duration_ms", descending=False)).json()["data"]["items"]
    assert [row["agent_id"] for row in ascending] == list(range(1, 10))
    assert (await get(app, page=100)).json()["data"]["items"] == []
    reader.assert_called_with(app.state.monitoring, tenant="a", start=DAY, end=DAY, groups=[], agent_id=None)


@pytest.mark.asyncio
async def test_rankings_choose_exact_top_five_with_stable_ties(view_app):
    app, _ = view_app
    data = (await get(app, "/rankings")).json()["data"]
    assert [row["agent_id"] for row in data] == [8, 6, 7, 4, 5]


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/trends", "/rankings"])
@pytest.mark.parametrize("actor,target,expected", [("OPS", "b", 403), ("USER", "a", 403), ("SU", "b", 200)])
async def test_all_views_apply_tenant_permissions(view_app, suffix, actor, target, expected):
    app, reader = view_app
    app.dependency_overrides[authenticate] = lambda: CurrentUser("test", "a", actor)
    assert (await get(app, suffix, tenant_id=target)).status_code == expected
    if expected == 403:
        reader.assert_not_called()
    else:
        assert reader.call_args.kwargs["tenant"] == "b"


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix,invalid", [("", {"page": 0}), ("", {"page_size": 101}),
    ("", {"sort_by": "success_rate"}), ("", {"search": "a" * 101}),
    ("/trends", {"end_date": PREVIOUS.isoformat()}), ("/rankings", {"agent_id": 0})])
async def test_view_parameter_validation(view_app, suffix, invalid):
    app, reader = view_app
    assert (await get(app, suffix, **invalid)).status_code == 422
    reader.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/trends", "/rankings"])
@pytest.mark.parametrize("configured", [False, True])
async def test_views_sanitize_dependency_failures(view_app, suffix, configured):
    app, reader = view_app
    if configured:
        reader.side_effect = RuntimeError("private database credentials")
    else:
        del app.state.monitoring
    response = await get(app, suffix)
    assert response.status_code == 503 and "private database credentials" not in response.text
