# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Agent list ordering uses published values without losing nulls or exact integers."""

from copy import deepcopy
from datetime import date
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from management.services.permission.identity.session import authenticate
from ops.api import monitoring
from ops.monitoring.agent_tokens import AgentTokenUsage
from permissions import rbac
from permissions.models import CurrentUser


DAY = date(2026, 11, 19)
STATUS = {"data_as_of": None, "coverage_state": "partial", "is_stale": True}
ORDER = [
    ("a", 1, "10", 0.5), ("a", 2, "2", 1.0), ("a", 3, "10", 0.5),
    ("a", 4, "0", 0.0), ("a", 5, None, None), ("a", 6, None, None),
    ("a", 7, "9007199254740992", 0.75), ("a", 8, "9007199254740993", 0.25),
    ("b", 1, "10", 0.5), ("a", 10, None, None),
]
EXPECTED = {
    ("total_tokens", False): [("a", n) for n in (4, 2, 9, 1, 3)] + [("b", 1)]
                            + [("a", n) for n in (7, 8, 5, 6, 10)],
    ("total_tokens", True): [("a", n) for n in (8, 7, 1, 3)] + [("b", 1)]
                           + [("a", n) for n in (9, 2, 4, 5, 6, 10)],
    ("success_rate", False): [("a", n) for n in (4, 8, 1, 3)] + [("b", 1)]
                            + [("a", n) for n in (7, 2, 5, 6, 9, 10)],
    ("success_rate", True): [("a", n) for n in (2, 7, 1, 3)] + [("b", 1)]
                           + [("a", n) for n in (8, 4, 5, 6, 9, 10)],
}


def token_usage(value):
    return {"tokens": {"total_tokens": {
        "value": value, "known_count": int(value is not None), "eligible_count": 2,
        "coverage_rate": 0.5 if value is not None else 0.0,
    }}, "token_status": dict(STATUS)}


@pytest.fixture
def sorting_app(monkeypatch):
    app = FastAPI()
    app.include_router(monitoring.ops_router)
    app.state.monitoring = object()
    app.dependency_overrides[authenticate] = lambda: CurrentUser("operator", "a", "SU")
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}, "SU": {"ops.dashboard:read"}})
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    items = [{"tenant_id": tenant, "agent_id": agent, "name": f"agent-{agent}",
              "metrics": {"success_rate": rate}} for tenant, agent, _, rate in reversed(ORDER)]
    items[0]["metrics"] = None
    usage = {(tenant, agent): token_usage(value) for tenant, agent, value, _ in ORDER if agent != 6}
    usage["a", 10] = {"tokens": {}, "token_status": dict(STATUS)}
    usage["a", 9] = token_usage("3")
    views = Mock(return_value=(items, 10, [], dict(STATUS)))
    tokens = Mock(return_value=AgentTokenUsage({}, dict(STATUS), usage, {}))
    monkeypatch.setattr(monitoring, "read_agent_views", views)
    monkeypatch.setattr(monitoring, "read_agent_tokens", tokens)
    return app, views, tokens


async def get(app, **params):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops") as client:
        return await client.get("/ops/v1/monitoring/agents", params={
            "start_date": DAY.isoformat(), "end_date": DAY.isoformat(), **params,
        })


@pytest.mark.asyncio
@pytest.mark.parametrize("metric,descending", EXPECTED)
async def test_new_sort_keys_keep_exact_values_nulls_and_stable_tenant_agent_ties(sorting_app, metric, descending):
    app, _, tokens = sorting_app
    original = deepcopy(tokens.return_value.agents)
    response = await get(app, sort_by=metric, descending=descending)
    assert response.status_code == 200
    body = response.json()
    rows = body["data"]["items"]
    assert [(row["tenant_id"], row["agent_id"]) for row in rows] == EXPECTED[metric, descending]
    assert body["data"]["total"] == 11 and body["data"]["current_agent_count"] == 10
    assert body["token_status"] == STATUS
    for row in rows:
        identity = row["tenant_id"], row["agent_id"]
        if identity in original:
            assert row["tokens"] == original[identity]["tokens"]
            assert row["token_status"] == original[identity]["token_status"]
    assert tokens.return_value.agents == original
    by_id = {row["agent_id"]: row for row in rows if row["tenant_id"] == "a"}
    assert by_id[4]["tokens"]["total_tokens"]["value"] == "0"
    assert by_id[4]["metrics"]["success_rate"] == 0.0
    assert by_id[5]["tokens"]["total_tokens"]["value"] is None
    assert by_id[5]["metrics"]["success_rate"] is None
    assert by_id[9]["metrics"] is None and not by_id[9]["is_current"]


@pytest.mark.asyncio
@pytest.mark.parametrize("metric,descending", EXPECTED)
async def test_pages_slice_the_full_stable_order_and_repeat_identically(sorting_app, metric, descending):
    app, _, _ = sorting_app
    identities = []
    for page in range(1, 7):
        response = await get(app, sort_by=metric, descending=descending, page=page, page_size=2)
        assert response.status_code == 200
        assert response.json() == (await get(
            app, sort_by=metric, descending=descending, page=page, page_size=2,
        )).json()
        identities.extend((row["tenant_id"], row["agent_id"]) for row in response.json()["data"]["items"])
    assert identities == EXPECTED[metric, descending]


@pytest.mark.asyncio
@pytest.mark.parametrize("metric", ["total_tokens", "success_rate"])
async def test_sorting_preserves_authorized_selection_for_both_published_readers(sorting_app, metric):
    app, views, tokens = sorting_app
    selected = views.return_value[0][-1:]
    views.return_value = selected, 1, [], dict(STATUS)
    tokens.return_value = AgentTokenUsage({}, dict(STATUS), {("a", 1): token_usage("10")}, {})
    response = await get(app, sort_by=metric, tenant_id="a", group_ids=[12, 13], agent_id=1,
                         start_date="2026-11-18", search="AGENT-1")
    assert response.status_code == 200
    assert [row["agent_id"] for row in response.json()["data"]["items"]] == [1]
    selection = dict(tenant="a", start=date(2026, 11, 18), end=DAY, groups=[12, 13], agent_id=1)
    views.assert_called_once_with(app.state.monitoring, **selection)
    assert tokens.call_count == 1
    assert {key: value for key, value in tokens.call_args.kwargs.items() if key != "identities"} == selection
    assert set(tokens.call_args.kwargs["identities"]) == {("a", 1)}


@pytest.mark.asyncio
@pytest.mark.parametrize("metric", ["total_tokens", "success_rate"])
async def test_foreign_tenant_is_rejected_before_either_sorting_reader(sorting_app, metric):
    app, views, tokens = sorting_app
    app.dependency_overrides[authenticate] = lambda: CurrentUser("operator", "a", "OPS")
    assert (await get(app, sort_by=metric, tenant_id="b")).status_code == 403
    views.assert_not_called()
    tokens.assert_not_called()


@pytest.mark.asyncio
async def test_unsupported_sort_key_remains_a_validation_error(sorting_app):
    app, views, tokens = sorting_app
    assert (await get(app, sort_by="unsupported_metric")).status_code == 422
    views.assert_not_called()
    tokens.assert_not_called()
