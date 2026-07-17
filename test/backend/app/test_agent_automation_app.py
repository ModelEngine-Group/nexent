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
    monkeypatch.setattr(
        agent_automation_app,
        "get_current_user_id",
        lambda authorization: ("user", "tenant"),
    )
    monkeypatch.setattr(
        agent_automation_app.agent_automation_facade,
        "list_tasks",
        lambda tenant_id, user_id, status=None, search=None: [
            {
                "task_id": 1,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "status": status or "ACTIVE",
                "search": search,
            }
        ],
    )

    response = _client().get(
        "/agent/automations?status=PAUSED&search=%E5%A4%A9%E6%B0%94",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json()["data"][0] == {
        "task_id": 1,
        "tenant_id": "tenant",
        "user_id": "user",
        "status": "PAUSED",
        "search": "天气",
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


def test_chat_proposal_can_be_updated(monkeypatch):
    captured = {}

    async def fake_update_proposal(proposal_id, request, tenant_id, user_id):
        captured.update({
            "proposal_id": proposal_id,
            "request": request,
            "tenant_id": tenant_id,
            "user_id": user_id,
        })
        return {
            "proposal_id": proposal_id,
            "task": {"title": request.title},
        }

    monkeypatch.setattr(agent_automation_app, "get_current_user_id", lambda authorization: ("user", "tenant"))
    monkeypatch.setattr(
        agent_automation_app.agent_automation_facade,
        "update_proposal",
        fake_update_proposal,
    )

    response = _client().patch(
        "/agent/automations/proposals/7",
        headers={"Authorization": "Bearer token"},
        json={"title": "修改后的任务"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["task"]["title"] == "修改后的任务"
    assert captured["proposal_id"] == 7
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


def test_delete_run_endpoint_uses_authenticated_owner(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        agent_automation_app,
        "get_current_user_id",
        lambda authorization: ("user", "tenant"),
    )

    def fake_delete_run(run_id, tenant_id, user_id):
        captured.update({
            "run_id": run_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
        })
        return True

    monkeypatch.setattr(
        agent_automation_app.agent_automation_facade,
        "delete_run",
        fake_delete_run,
    )

    response = _client().delete(
        "/agent/automations/runs/7",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json()["data"] is True
    assert captured == {
        "run_id": 7,
        "tenant_id": "tenant",
        "user_id": "user",
    }
