# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Agent Token HTTP fields, orphan resource projection and authorization boundaries."""

from datetime import date
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from gateway.authentication.auth import authenticate
from ops.api import monitoring
from ops.monitoring.agent_tokens import AgentTokenUsage
from permissions import rbac
from permissions.models import CurrentUser


DAY = date(2026, 11, 19)


@pytest.fixture
def app(monkeypatch):
    app = FastAPI()
    app.include_router(monitoring.ops_router)
    app.state.monitoring = object()
    app.dependency_overrides[authenticate] = lambda: CurrentUser("operator", "a", "OPS")
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}})
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    status = {"data_as_of": None, "coverage_state": "partial", "is_stale": False}
    metrics = {"execution_count": 1, "avg_duration_ms": 25}
    monkeypatch.setattr(monitoring, "read_agents", Mock(return_value=(metrics, status)))
    monkeypatch.setattr(monitoring, "read_agent_views", Mock(return_value=(
        [{"tenant_id": "a", "agent_id": 21, "name": "root", "metrics": metrics}], 1,
        [{"statistic_date": DAY, **metrics}], status,
    )))
    tokens = {"total_tokens": {"value": "12", "known_count": 1, "eligible_count": 2, "coverage_rate": 0.5}}
    token_status = {"data_as_of": None, "coverage_state": "covered", "is_stale": True}
    usage = {"tokens": tokens, "token_status": token_status}
    reader = Mock(return_value=AgentTokenUsage(tokens, token_status,
                                               {("a", 21): usage, ("a", 24): usage}, {DAY: usage}))
    monkeypatch.setattr(monitoring, "read_agent_tokens", reader)
    return app, reader, tokens, token_status


async def get(app, suffix, **params):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops") as client:
        return await client.get("/ops/v1/monitoring/agents" + suffix,
                                params={"start_date": DAY.isoformat(), "end_date": DAY.isoformat(), **params})


@pytest.mark.asyncio
async def test_summary_exposes_independently_published_token_values_and_status(app):
    api, reader, tokens, status = app
    response = await get(api, "/summary", agent_id=21, group_ids=[12, 13])
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["execution_count"] == 1
    assert body["tokens"] == tokens and body["token_status"] == status
    assert not body["is_stale"] and body["token_status"]["is_stale"]
    reader.assert_called_once_with(api.state.monitoring, tenant="a", start=DAY, end=DAY,
                                   groups=[12, 13], agent_id=21)


@pytest.mark.asyncio
async def test_directory_keeps_token_only_historical_resources_without_inflating_inventory(app):
    api, _, tokens, status = app
    body = (await get(api, "")).json()
    assert body["data"]["current_agent_count"] == 1 and body["data"]["total"] == 2
    current, historical = body["data"]["items"]
    assert current["tokens"] == tokens and current["metrics"]["execution_count"] == 1
    assert historical["agent_id"] == 24 and historical["metrics"] is None and not historical["is_current"]
    assert historical["tokens"] == tokens and body["token_status"] == status


@pytest.mark.asyncio
async def test_trend_days_have_token_values_and_their_model_publication_status(app):
    api, _, tokens, status = app
    day, = (await get(api, "/trends")).json()["data"]
    assert day["statistic_date"] == DAY.isoformat() and day["execution_count"] == 1
    assert day["tokens"] == tokens and day["token_status"] == status


@pytest.mark.asyncio
async def test_execution_rankings_keep_their_existing_query_dependency(app):
    api, reader, _, _ = app
    response = await get(api, "/rankings")
    assert response.status_code == 200
    reader.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["/summary", "", "/trends"])
async def test_token_storage_errors_are_sanitized(app, suffix):
    api, reader, _, _ = app
    reader.side_effect = RuntimeError("private ES endpoint")
    response = await get(api, suffix)
    assert response.status_code == 503 and "private ES endpoint" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["/summary", "", "/trends"])
async def test_foreign_tenant_is_rejected_before_reading_tokens(app, suffix):
    api, reader, _, _ = app
    assert (await get(api, suffix, tenant_id="b")).status_code == 403
    reader.assert_not_called()
