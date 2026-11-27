# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Config and Runtime routing, authorization, and readiness failures."""

from types import SimpleNamespace

import pytest

from shared.http import assert_status, client
from shared.split_service_boundary import downstream_client, signed_headers, split_service_apps


@pytest.mark.stage("D2")
@pytest.mark.case_id("API-163")
@pytest.mark.parametrize(
    ("audience", "owned_method", "owned_path", "wrong_method", "wrong_path"),
    [
        ("management", "GET", "/model/list", "POST", "/voice/connectivity"),
        ("runtime", "POST", "/voice/connectivity", "GET", "/model/list"),
    ],
)
async def test_split_services_reject_cross_routed_and_unauthenticated_operations(
    split_service_apps, audience, owned_method, owned_path, wrong_method, wrong_path
):
    async with downstream_client(split_service_apps[audience], audience) as api:
        protected = await api.request(owned_method, owned_path)
        wrong = await api.request(wrong_method, wrong_path, headers=signed_headers(audience, wrong_method, wrong_path))

    assert_status(protected, 401)
    assert protected.json() == {"message": "Gateway identity required or invalid"}
    assert_status(wrong, 404)


@pytest.mark.stage("D2")
@pytest.mark.case_id("API-163")
@pytest.mark.parametrize("audience", ["management", "runtime"])
@pytest.mark.parametrize(("manager_state", "stuck_count"), [("draining", 0), ("running", 1)])
async def test_direct_readiness_rejects_draining_and_stuck_manager(
    split_service_apps, monkeypatch, audience, manager_state, stuck_count
):
    app = split_service_apps[audience]
    snapshot = SimpleNamespace(state=manager_state, stuck_count=stuck_count)
    monkeypatch.setattr(app.state, "thread_manager", SimpleNamespace(snapshot=lambda: snapshot))
    async with downstream_client(app, audience) as api:
        live = await api.get("/health/live")
        ready = await api.get("/health/ready")

    assert_status(live, 200)
    assert live.json() == {"status": "alive"}
    assert_status(ready, 503)
    assert ready.json() == {"status": "not_ready", "manager_state": manager_state, "stuck_count": stuck_count}


@pytest.mark.stage("D2")
@pytest.mark.case_id("API-163")
async def test_gateway_rejects_anonymous_and_private_requests():
    async with client("northbound") as api:
        assert_status(await api.get("/api/agent/automations"), 401)
        assert_status(await api.post("/api/voice/connectivity"), 401)
        assert_status(await api.get("/api/openapi.json"), 404)
        assert_status(await api.get("/api/internal/thread-capacity"), 404)
