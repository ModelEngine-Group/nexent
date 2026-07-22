import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from apps import agent_automation_app
from apps.app_factory import create_app
from consts.exceptions import UnauthorizedError
from services.agent_automation.errors import (
    AgentAutomationError,
    AutomationConversationAlreadyBoundError,
    AutomationNotFoundError,
)
from services.agent_automation.models import (
    AutomationProposalPatchRequest,
    AutomationTaskPatchRequest,
)


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
        lambda tenant_id, user_id, status=None, search=None, agent_name=None: [
            {
                "task_id": 1,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "status": status or "ACTIVE",
                "search": search,
                "agent_name": agent_name,
            }
        ],
    )

    response = _client().get(
        "/agent/automations?status=PAUSED&search=%E5%A4%A9%E6%B0%94&agent_name=%E5%8A%A9%E6%89%8B",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json()["data"][0] == {
        "task_id": 1,
        "tenant_id": "tenant",
        "user_id": "user",
        "status": "PAUSED",
        "search": "天气",
        "agent_name": "助手",
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


def test_map_error_uses_domain_specific_http_statuses():
    cases = [
        (AutomationNotFoundError("missing"), 404),
        (AutomationConversationAlreadyBoundError("bound"), 409),
        (AgentAutomationError("invalid", {"field": "schedule"}), 400),
    ]

    for error, expected_status in cases:
        mapped = agent_automation_app._map_error(error)
        assert mapped.status_code == expected_status
        assert mapped.detail == {
            "code": error.error_code,
            "message": error.message,
            "details": error.details,
        }


@pytest.mark.asyncio
async def test_management_handlers_delegate_to_authenticated_facade(monkeypatch):
    monkeypatch.setattr(
        agent_automation_app,
        "get_current_user_id",
        lambda authorization: ("user", "tenant"),
    )
    facade = agent_automation_app.agent_automation_facade
    monkeypatch.setattr(facade, "confirm_proposal", AsyncMock(return_value={"task_id": 1}))
    monkeypatch.setattr(facade, "get_task", MagicMock(return_value={"task_id": 1}))
    monkeypatch.setattr(facade, "patch_task", AsyncMock(return_value={"title": "updated"}))
    monkeypatch.setattr(facade, "pause_task", MagicMock(return_value={"status": "PAUSED"}))
    monkeypatch.setattr(facade, "resume_task", MagicMock(return_value={"status": "ACTIVE"}))
    monkeypatch.setattr(facade, "run_task_now", AsyncMock(return_value={"run_id": 2}))
    monkeypatch.setattr(facade, "delete_task", MagicMock(return_value=True))
    monkeypatch.setattr(facade, "list_runs", MagicMock(return_value=[{"run_id": 2}]))
    monkeypatch.setattr(facade, "cancel_run", MagicMock(return_value={"status": "CANCELED"}))
    monkeypatch.setattr(
        facade,
        "get_task_for_conversation",
        MagicMock(return_value={"conversation_id": 9}),
    )

    assert (await agent_automation_app.confirm_proposal(7, None, "token")).data == {"task_id": 1}
    assert (await agent_automation_app.get_task(1, "token")).data == {"task_id": 1}
    assert (
        await agent_automation_app.patch_task(
            1,
            AutomationTaskPatchRequest(title="updated"),
            "token",
        )
    ).data == {"title": "updated"}
    assert (await agent_automation_app.pause_task(1, "token")).data == {"status": "PAUSED"}
    assert (await agent_automation_app.resume_task(1, "token")).data == {"status": "ACTIVE"}
    assert (await agent_automation_app.run_task_now(1, "token")).data == {"run_id": 2}
    assert (await agent_automation_app.delete_task(1, "token")).data is True
    assert (await agent_automation_app.list_runs(1, "token")).data == [{"run_id": 2}]
    assert (await agent_automation_app.cancel_run(2, "token")).data == {"status": "CANCELED"}
    assert (await agent_automation_app.get_conversation_automation(9, "token")).data == {
        "conversation_id": 9
    }

    facade.confirm_proposal.assert_awaited_once()
    facade.patch_task.assert_awaited_once()
    facade.run_task_now.assert_awaited_once_with(1, "tenant", "user")


@pytest.mark.parametrize(
    ("path", "method", "facade_method", "payload"),
    [
        ("/agent/automations/proposals", "post", "create_proposal", {"agent_id": 1, "message": "run"}),
        (
            "/agent/automations/proposals/1/confirm",
            "post",
            "confirm_proposal",
            {},
        ),
        (
            "/agent/automations/proposals/1",
            "patch",
            "update_proposal",
            {"title": "updated"},
        ),
    ],
)
def test_proposal_endpoints_map_domain_errors(monkeypatch, path, method, facade_method, payload):
    monkeypatch.setattr(
        agent_automation_app,
        "get_current_user_id",
        lambda authorization: ("user", "tenant"),
    )
    monkeypatch.setattr(
        agent_automation_app.agent_automation_facade,
        facade_method,
        AsyncMock(side_effect=AutomationNotFoundError("missing")),
    )

    response = getattr(_client(), method)(path, json=payload)

    assert response.status_code == 404
    assert response.json()["message"]["code"] == "AUTOMATION_TASK_NOT_FOUND"


@pytest.mark.parametrize(
    ("path", "method", "facade_method", "payload"),
    [
        ("/agent/automations/proposals", "post", "create_proposal", {"agent_id": 1, "message": "run"}),
        (
            "/agent/automations/proposals/1/confirm",
            "post",
            "confirm_proposal",
            {},
        ),
        (
            "/agent/automations/proposals/1",
            "patch",
            "update_proposal",
            {"title": "updated"},
        ),
    ],
)
def test_proposal_endpoints_hide_unexpected_failures_behind_500(
    monkeypatch,
    path,
    method,
    facade_method,
    payload,
):
    monkeypatch.setattr(
        agent_automation_app,
        "get_current_user_id",
        lambda authorization: ("user", "tenant"),
    )
    monkeypatch.setattr(
        agent_automation_app.agent_automation_facade,
        facade_method,
        AsyncMock(side_effect=RuntimeError("database unavailable")),
    )

    response = getattr(_client(), method)(path, json=payload)

    assert response.status_code == 500


def test_list_and_conversation_endpoints_map_unexpected_failures(monkeypatch):
    monkeypatch.setattr(
        agent_automation_app,
        "get_current_user_id",
        lambda authorization: ("user", "tenant"),
    )
    monkeypatch.setattr(
        agent_automation_app.agent_automation_facade,
        "list_tasks",
        MagicMock(side_effect=RuntimeError("list failed")),
    )
    list_response = _client().get("/agent/automations")
    assert list_response.status_code == 500

    monkeypatch.setattr(
        agent_automation_app.agent_automation_facade,
        "get_task_for_conversation",
        MagicMock(side_effect=RuntimeError("lookup failed")),
    )
    conversation_response = _client().get("/conversation/9/automation")
    assert conversation_response.status_code == 500


@pytest.mark.asyncio
async def test_management_handlers_map_domain_errors(monkeypatch):
    monkeypatch.setattr(
        agent_automation_app,
        "get_current_user_id",
        lambda authorization: ("user", "tenant"),
    )
    facade = agent_automation_app.agent_automation_facade
    error = AutomationNotFoundError("missing")
    cases = [
        ("get_task", MagicMock(side_effect=error), lambda: agent_automation_app.get_task(1, "token")),
        (
            "patch_task",
            AsyncMock(side_effect=error),
            lambda: agent_automation_app.patch_task(
                1,
                AutomationTaskPatchRequest(title="updated"),
                "token",
            ),
        ),
        ("pause_task", MagicMock(side_effect=error), lambda: agent_automation_app.pause_task(1, "token")),
        ("resume_task", MagicMock(side_effect=error), lambda: agent_automation_app.resume_task(1, "token")),
        ("run_task_now", AsyncMock(side_effect=error), lambda: agent_automation_app.run_task_now(1, "token")),
        ("delete_task", MagicMock(side_effect=error), lambda: agent_automation_app.delete_task(1, "token")),
        ("list_runs", MagicMock(side_effect=error), lambda: agent_automation_app.list_runs(1, "token")),
        ("cancel_run", MagicMock(side_effect=error), lambda: agent_automation_app.cancel_run(1, "token")),
        ("delete_run", MagicMock(side_effect=error), lambda: agent_automation_app.delete_run(1, "token")),
    ]

    for method_name, mock_method, invoke in cases:
        monkeypatch.setattr(facade, method_name, mock_method)
        with pytest.raises(HTTPException) as exc_info:
            await invoke()
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_handlers_preserve_authentication_http_errors(monkeypatch):
    def raise_unauthorized(authorization):
        raise UnauthorizedError("invalid token")

    monkeypatch.setattr(agent_automation_app, "get_current_user_id", raise_unauthorized)
    calls = [
        lambda: agent_automation_app.create_proposal(
            agent_automation_app.AutomationProposalCreateRequest(agent_id=1, message="run"),
            "token",
        ),
        lambda: agent_automation_app.confirm_proposal(1, None, "token"),
        lambda: agent_automation_app.update_proposal(
            1,
            AutomationProposalPatchRequest(title="updated"),
            "token",
        ),
        lambda: agent_automation_app.list_tasks(authorization="token"),
        lambda: agent_automation_app.get_conversation_automation(9, "token"),
    ]

    for invoke in calls:
        with pytest.raises(HTTPException) as exc_info:
            await invoke()
        assert exc_info.value.status_code == 401
