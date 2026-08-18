from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.health_service import install_health_contract


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


def test_drain_endpoint_is_not_exposed():
    app = FastAPI()
    install_health_contract(app)

    assert TestClient(app).post("/health/drain").status_code == 404
