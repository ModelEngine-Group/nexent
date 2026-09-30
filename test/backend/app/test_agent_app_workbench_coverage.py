from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request

from test.backend.app import test_agent_app as legacy


agent_app = __import__("apps.agent_app", fromlist=["get_workbench_bootstrap_api"])


@pytest.mark.asyncio
async def test_workbench_bootstrap_returns_profile(monkeypatch):
    profile = {"display_name": "Workbench", "default_skill_resources": [{"skill_id": 1}]}
    monkeypatch.setattr(agent_app, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(agent_app, "get_current_user_id", lambda _authorization: ("user-a", "tenant-a"))
    monkeypatch.setattr(agent_app, "build_workbench_main_profile", MagicMock(return_value=profile))

    response = await agent_app.get_workbench_bootstrap_api("Bearer token")

    assert response["data"]["schema_version"] == 3
    assert response["data"]["generic_agent"] == profile
    assert response["data"]["modes"]["multi_agent_chat"]["enabled"] is True
    assert response["data"]["modes"]["agent_create"]["enabled"] is False


@pytest.mark.asyncio
async def test_workbench_bootstrap_lazily_initializes_missing_agent(monkeypatch):
    profile = {"display_name": "Workbench", "default_skill_resources": []}
    load = MagicMock(side_effect=[RuntimeError("missing"), profile])
    initialize = AsyncMock()
    monkeypatch.setattr(agent_app, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(agent_app, "get_current_user_id", lambda _authorization: ("user-a", "tenant-a"))
    monkeypatch.setattr(agent_app, "build_workbench_main_profile", load)
    monkeypatch.setattr(agent_app, "run_blocking", initialize)

    response = await agent_app.get_workbench_bootstrap_api("Bearer token")

    initialize.assert_awaited_once_with(
        "workbench-bootstrap",
        agent_app.ensure_workbench_main_agent,
        "tenant-a",
        "system",
    )
    assert response["data"]["generic_agent"] == profile


@pytest.mark.asyncio
async def test_workbench_bootstrap_uses_safe_fallback_after_initialization_failure(monkeypatch):
    monkeypatch.setattr(agent_app, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(agent_app, "get_current_user_id", lambda _authorization: ("user-a", "tenant-a"))
    monkeypatch.setattr(
        agent_app,
        "build_workbench_main_profile",
        MagicMock(side_effect=RuntimeError("missing")),
    )
    monkeypatch.setattr(agent_app, "run_blocking", AsyncMock(side_effect=RuntimeError("failed")))

    response = await agent_app.get_workbench_bootstrap_api("Bearer token")

    assert response["data"]["generic_agent"] == {
        "display_name": "Nexent Workbench",
        "default_skill_resources": [],
    }


@pytest.mark.asyncio
async def test_workbench_bootstrap_is_hidden_when_disabled(monkeypatch):
    monkeypatch.setattr(agent_app, "ENABLE_AGENT_WORKBENCH", False)

    with pytest.raises(HTTPException) as caught:
        await agent_app.get_workbench_bootstrap_api("Bearer token")
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_capability_preview_returns_locked_defaults(monkeypatch):
    data = {"agent_id": 7, "version_no": 3}
    monkeypatch.setattr(agent_app, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(agent_app, "get_current_user_id", lambda _authorization: ("user-a", "tenant-a"))
    preview = MagicMock(return_value=data)
    monkeypatch.setattr(agent_app, "build_workbench_capability_preview", preview)
    request = agent_app.WorkbenchCapabilityPreviewRequest(agent_id=7, version_no=3)

    response = await agent_app.preview_workbench_capabilities_api(request, "Bearer token")

    assert response == {"code": 0, "message": "success", "data": data}
    preview.assert_called_once_with(
        agent_id=7,
        version_no=3,
        tenant_id="tenant-a",
        user_id="user-a",
    )


@pytest.mark.asyncio
async def test_capability_preview_is_hidden_when_disabled(monkeypatch):
    monkeypatch.setattr(agent_app, "ENABLE_AGENT_WORKBENCH", False)

    with pytest.raises(HTTPException) as caught:
        await agent_app.preview_workbench_capabilities_api(
            agent_app.WorkbenchCapabilityPreviewRequest(agent_id=7),
            "Bearer token",
        )
    assert caught.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (
            agent_app.WorkbenchError("WORKBENCH_DISABLED", status_code=404),
            404,
            {"code": "WORKBENCH_DISABLED"},
        ),
        (
            agent_app.WorkbenchConfigVersionConflict(7),
            409,
            {"code": "WORKBENCH_CONFIG_VERSION_CONFLICT", "current_version": 7},
        ),
    ],
)
async def test_agent_run_maps_workbench_errors(monkeypatch, error, status, detail):
    monkeypatch.setattr(agent_app, "run_agent_stream", AsyncMock(side_effect=error))
    request = agent_app.AgentRequest(query="hello", agent_id=7)

    with pytest.raises(HTTPException) as caught:
        await agent_app.agent_run_api(
            request,
            Request(scope={"type": "http", "headers": []}),
            "Bearer token",
        )
    assert caught.value.status_code == status
    assert caught.value.detail == detail


@pytest.mark.asyncio
async def test_nl2agent_history_is_hidden_when_workbench_disabled(monkeypatch):
    monkeypatch.setattr(agent_app, "ENABLE_AGENT_WORKBENCH", False)
    request = agent_app.NL2AgentRunRequest(
        query="Create an agent", agent_id=7, persist_history=True
    )

    with pytest.raises(HTTPException) as caught:
        await agent_app.nl2agent_run_api(
            request,
            Request(scope={"type": "http", "headers": []}),
            "Bearer token",
            None,
        )
    assert caught.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (agent_app.WorkbenchError("AGENT_NOT_RUNNABLE", status_code=409), 409, {"code": "AGENT_NOT_RUNNABLE"}),
        (agent_app.ForbiddenError("forbidden"), 403, "forbidden"),
        (ValueError("missing"), 422, {"code": "WORKBENCH_RESOURCE_UNAVAILABLE"}),
        (agent_app.ValidationError("invalid"), 422, {"code": "WORKBENCH_RESOURCE_UNAVAILABLE"}),
    ],
)
async def test_capability_preview_maps_domain_errors(monkeypatch, error, status, detail):
    monkeypatch.setattr(agent_app, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(agent_app, "get_current_user_id", lambda _authorization: ("user-a", "tenant-a"))
    monkeypatch.setattr(
        agent_app,
        "build_workbench_capability_preview",
        MagicMock(side_effect=error),
    )
    request = agent_app.WorkbenchCapabilityPreviewRequest(agent_id=7)

    with pytest.raises(HTTPException) as caught:
        await agent_app.preview_workbench_capabilities_api(request, "Bearer token")
    assert caught.value.status_code == status
    assert caught.value.detail == detail
