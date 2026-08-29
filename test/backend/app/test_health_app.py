from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.apps.health_app import install_health_contract


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
