# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Config and Runtime process health and router ownership."""

import httpx
import pytest

from shared.config import readiness_url
from shared.deployment_guard import assert_service_available
from shared.http import DEFAULT_TIMEOUT, assert_status
from shared.split_service_boundary import downstream_client, signed_headers, split_service_apps


@pytest.mark.stage("D2")
@pytest.mark.case_id("API-162")
@pytest.mark.parametrize("service", ["config", "runtime"])
async def test_deployed_service_is_live_and_ready(service):
    assert_service_available(service)
    ready_url = httpx.URL(readiness_url(service))
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, trust_env=False) as api:
        live = await api.get(ready_url.join("live"))
        ready = await api.get(ready_url)

    assert_status(live, 200)
    assert live.json() == {"status": "alive"}
    assert_status(ready, 200)
    assert ready.json() == {"status": "ready", "manager_state": "running", "stuck_count": 0}


@pytest.mark.stage("D2")
@pytest.mark.case_id("API-162")
async def test_runtime_and_config_service_openapi_expose_only_owned_router_sets(split_service_apps):
    path = "/openapi.json"
    paths = {}
    for audience, app in split_service_apps.items():
        async with downstream_client(app, audience) as api:
            response = await api.get(path, headers=signed_headers(audience, "GET", path))
        assert_status(response, 200)
        paths[audience] = response.json()["paths"]
        assert paths[audience].keys().isdisjoint({"/health/live", "/health/ready", "/internal/thread-capacity"})

    assert "get" in paths["management"]["/model/list"]
    assert "put" in paths["management"]["/conversation/create"]
    assert "post" in paths["runtime"]["/voice/connectivity"]
    assert "/voice/connectivity" not in paths["management"]
    assert paths["runtime"].keys().isdisjoint({"/model/list", "/conversation/create"})


@pytest.mark.stage("D2")
@pytest.mark.case_id("API-162")
@pytest.mark.parametrize(("audience", "service"), [("management", "config"), ("runtime", "runtime")])
async def test_direct_capacity_snapshot_matches_readiness(split_service_apps, audience, service):
    path = "/internal/thread-capacity"
    async with downstream_client(split_service_apps[audience], audience) as api:
        capacity = await api.get(path, headers=signed_headers(audience, "GET", path))
        ready = await api.get("/health/ready")

    assert_status(capacity, 200)
    snapshot = capacity.json()
    assert snapshot["service_name"] == service
    state = snapshot["state"]
    stuck_count = snapshot["stuck_count"]
    is_ready = state == "running" and stuck_count == 0
    assert_status(ready, 200 if is_ready else 503)
    assert ready.json() == {
        "status": "ready" if is_ready else "not_ready",
        "manager_state": state,
        "stuck_count": stuck_count,
    }
