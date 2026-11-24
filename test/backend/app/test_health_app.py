# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import threading
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from infrastructure.system_configuration.runtime import SystemConfigurationRuntime
from backend.http.server.app_factory import create_app
from backend.http.server.health import install_health_contract

from test.backend.configuration.test_catalog import EXPECTED_DEFAULTS


def test_lost_coordination_changes_readiness_without_polling_redis_or_kubernetes():
    app = FastAPI()
    install_health_contract(app)
    lost = threading.Event()
    app.state.sandbox_coordinator = SimpleNamespace(lost_coordination=lost)
    configuration = SimpleNamespace(is_ready=True)
    app.state.configuration_runtime = configuration
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        lost.set()
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready", "reason": "coordination_unknown"}

        configuration.is_ready = False
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready", "configuration_ready": False}
        assert response.json()["configuration_ready"] is False
        assert client.get("/health/live").status_code == 200


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


def test_real_app_stays_unready_until_first_configuration_snapshot_arrives():
    release_recovery = threading.Event()
    load_count = 0

    async def loader():
        nonlocal load_count
        load_count += 1
        if load_count == 1:
            raise RuntimeError("database unavailable")
        if load_count == 2:
            await asyncio.to_thread(release_recovery.wait)
        return dict(EXPECTED_DEFAULTS)

    def unavailable_redis():
        raise RuntimeError("Redis unavailable; poll the database")

    runtime = SystemConfigurationRuntime(
        loader=loader,
        redis_factory=unavailable_redis,
        disconnected_interval=0.001,
    )

    @asynccontextmanager
    async def lifespan(app):
        await runtime.start()
        app.state.configuration_runtime = runtime
        try:
            yield
        finally:
            await runtime.stop()

    app = create_app(enable_monitoring=False, lifespan=lifespan)
    app.state.thread_manager = SimpleNamespace(
        snapshot=lambda: SimpleNamespace(
            state=SimpleNamespace(value="running"), stuck_count=0
        )
    )

    with TestClient(app) as client:
        initial = client.get("/health/ready")
        assert initial.status_code == 503
        assert initial.json() == {
            "status": "not_ready",
            "configuration_ready": False,
        }

        release_recovery.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            recovered = client.get("/health/ready")
            if recovered.status_code == 200:
                break
            time.sleep(0.01)
        assert recovered.status_code == 200
        assert runtime.get_snapshot().to_dict() == EXPECTED_DEFAULTS
        assert load_count >= 2
