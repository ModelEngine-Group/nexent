import os
import sys

from fastapi.testclient import TestClient


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from apps import agent_automation_app
from apps.app_factory import create_app
from consts.exceptions import UnauthorizedError


def _client():
    app = create_app(enable_monitoring=False)
    app.include_router(agent_automation_app.router)
    app.include_router(agent_automation_app.conversation_automation_router)
    return TestClient(app)


def test_list_tasks_http_smoke(monkeypatch):
    monkeypatch.setattr(agent_automation_app, "get_current_user_id", lambda authorization: ("user", "tenant"))
    monkeypatch.setattr(
        agent_automation_app.agent_automation_facade,
        "list_tasks",
        lambda tenant_id, user_id, status=None: [
            {
                "task_id": 1,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "status": status or "ACTIVE",
            }
        ],
    )

    response = _client().get("/agent/automations", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert response.json()["data"][0] == {
        "task_id": 1,
        "tenant_id": "tenant",
        "user_id": "user",
        "status": "ACTIVE",
    }


def test_direct_task_creation_endpoint_is_not_exposed():
    response = _client().post(
        "/agent/automations",
        headers={"Authorization": "Bearer token"},
        json={
            "title": "短周期任务",
            "agent_id": 1,
            "instruction": "频繁执行",
            "conversation_id": 123,
            "schedule_trigger": {
                "mode": "RECURRING",
                "rule_type": "INTERVAL",
                "timezone": "Asia/Shanghai",
                "start_at": "2030-01-01T09:00:00+08:00",
                "interval_seconds": 60,
            },
        },
    )

    assert response.status_code == 405


def test_chat_proposal_can_start_a_new_bound_conversation(monkeypatch):
    captured = {}

    async def fake_create_proposal(request, tenant_id, user_id):
        captured.update({
            "request": request,
            "tenant_id": tenant_id,
            "user_id": user_id,
        })
        return {
            "proposal_id": 7,
            "conversation_id": 321,
            "task": {"title": "周报"},
        }

    monkeypatch.setattr(agent_automation_app, "get_current_user_id", lambda authorization: ("user", "tenant"))
    monkeypatch.setattr(
        agent_automation_app.agent_automation_facade,
        "create_proposal",
        fake_create_proposal,
    )

    response = _client().post(
        "/agent/automations/proposals",
        headers={"Authorization": "Bearer token"},
        json={"agent_id": 7, "message": "每周发一个周报"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["conversation_id"] == 321
    assert captured["request"].conversation_id is None
    assert captured["tenant_id"] == "tenant"
    assert captured["user_id"] == "user"


def test_list_tasks_without_authorization_returns_401(monkeypatch):
    def raise_unauthorized(authorization):
        raise UnauthorizedError("No authorization header provided")

    monkeypatch.setattr(
        agent_automation_app,
        "get_current_user_id",
        raise_unauthorized,
    )
    response = _client().get("/agent/automations")

    assert response.status_code == 401
