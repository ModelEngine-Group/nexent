# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from management.utils.health import install_health_contract


def test_lost_coordination_changes_readiness_without_polling_redis_or_kubernetes():
    app = FastAPI()
    install_health_contract(app)
    lost = threading.Event()
    app.state.sandbox_coordinator = SimpleNamespace(lost_coordination=lost)
    with TestClient(app) as client:
        assert client.get('/health/ready').status_code == 200
        lost.set()
        response = client.get('/health/ready')
        assert response.status_code == 503 and response.json()['reason'] == 'coordination_unknown'
        assert client.get('/health/live').status_code == 200


def test_live_and_ready_are_dependency_free_process_health():
    app = FastAPI()
    install_health_contract(app)

    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "alive"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


def test_health_endpoints_are_not_exposed_in_openapi():
    app = FastAPI()
    install_health_contract(app)

    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "/health/live" not in paths
    assert "/health/ready" not in paths


def test_ready_follows_thread_manager_lifecycle():
    app = FastAPI()
    install_health_contract(app)
    manager = SimpleNamespace(
        snapshot=lambda: SimpleNamespace(
            state=SimpleNamespace(value="running"), stuck_count=0
        )
    )
    app.state.thread_manager = manager

    client = TestClient(app)
    assert client.get("/health/ready").json() == {
        "status": "ready",
        "manager_state": "running",
        "stuck_count": 0,
    }

    manager.snapshot = lambda: SimpleNamespace(
        state=SimpleNamespace(value="draining"), stuck_count=0
    )
    draining = client.get("/health/ready")
    assert draining.status_code == 503
    assert draining.json()["manager_state"] == "draining"

    manager.snapshot = lambda: SimpleNamespace(
        state=SimpleNamespace(value="running"), stuck_count=1
    )
    stuck = client.get("/health/ready")
    assert stuck.status_code == 503
    assert stuck.json()["stuck_count"] == 1
