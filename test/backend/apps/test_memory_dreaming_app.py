from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from apps import memory_dreaming_app


def app():
    app = FastAPI()
    app.include_router(memory_dreaming_app.router)
    return app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.mark.asyncio
async def test_ac009_missing_agent_id_is_422(client):
    response = await client.post("/memory/dreaming/run", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ac009_run_uses_authenticated_scope(monkeypatch, client):
    service = MagicMock()
    service.run.return_value = {"run_id": 1, "status": "completed"}
    monkeypatch.setattr(
        memory_dreaming_app, "get_memory_dreaming_service", lambda: service
    )
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("user-1", "tenant-1"),
    )
    response = await client.post(
        "/memory/dreaming/run",
        headers={"Authorization": "Bearer token"},
        json={"agent_id": "agent-1"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert service.run.call_args.kwargs["tenant_id"] == "tenant-1"
    assert service.run.call_args.kwargs["user_id"] == "user-1"
    assert service.run.call_args.kwargs["agent_id"] == "agent-1"


@pytest.mark.asyncio
async def test_ac009_audit_uses_authenticated_scope(monkeypatch, client):
    service = MagicMock()
    service.list_audits.return_value = [{"run_id": 2}]
    monkeypatch.setattr(
        memory_dreaming_app, "get_memory_dreaming_service", lambda: service
    )
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("user-2", "tenant-2"),
    )
    response = await client.get("/memory/dreaming/audit?agent_id=agent-2&run_id=2")
    assert response.status_code == 200
    service.list_audits.assert_called_once_with(
        "tenant-2", "user-2", agent_id="agent-2", run_id=2, limit=100
    )


@pytest.mark.asyncio
async def test_ac008_service_failure_maps_to_500(monkeypatch, client):
    service = MagicMock()
    service.run.side_effect = memory_dreaming_app.DreamingRunError("failed")
    monkeypatch.setattr(
        memory_dreaming_app, "get_memory_dreaming_service", lambda: service
    )
    monkeypatch.setattr(
        memory_dreaming_app,
        "get_current_user_id",
        lambda _authorization: ("user", "tenant"),
    )
    response = await client.post("/memory/dreaming/run", json={"agent_id": "agent"})
    assert response.status_code == 500
    assert response.json()["detail"] == "failed"
