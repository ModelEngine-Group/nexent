from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from test.backend.app import test_conversation_management_app as legacy


conversation_app = __import__(
    "backend.apps.conversation_management_app",
    fromlist=["update_conversation_workbench_config_endpoint"],
)


def _request():
    return conversation_app.WorkbenchConfigUpdateRequest.model_validate(
        {
            "expected_version": 2,
            "config": {
                "mode": "single_agent_chat",
                "agent_mounts": [{"agent_id": 7, "version_no": 3}],
            },
        }
    )


@pytest.mark.asyncio
async def test_update_workbench_config_returns_new_state(monkeypatch):
    update = MagicMock(return_value={"workbench_config_version": 3})
    monkeypatch.setattr(conversation_app, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(
        conversation_app,
        "get_current_user_id",
        lambda _authorization: ("user-a", "tenant-a"),
    )
    monkeypatch.setattr(
        conversation_app, "update_conversation_workbench_config_service", update
    )
    request = _request()

    response = await conversation_app.update_conversation_workbench_config_endpoint(
        42, request, "Bearer token"
    )

    assert response.data == {"workbench_config_version": 3}
    update.assert_called_once_with(
        conversation_id=42,
        config=request.config.model_dump(mode="json"),
        expected_version=2,
        user_id="user-a",
    )


@pytest.mark.asyncio
async def test_update_workbench_config_is_hidden_when_disabled(monkeypatch):
    monkeypatch.setattr(conversation_app, "ENABLE_AGENT_WORKBENCH", False)

    with pytest.raises(HTTPException) as caught:
        await conversation_app.update_conversation_workbench_config_endpoint(
            42, _request(), "Bearer token"
        )
    assert caught.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (conversation_app.ConversationNotFoundError("missing"), 404, "missing"),
        (
            conversation_app.WorkbenchConfigVersionConflict(5),
            409,
            {"code": "WORKBENCH_CONFIG_VERSION_CONFLICT", "current_version": 5},
        ),
        (
            conversation_app.WorkbenchError("AGENT_NOT_RUNNABLE", status_code=403),
            403,
            {"code": "AGENT_NOT_RUNNABLE"},
        ),
        (ValueError("invalid"), 422, {"code": "WORKBENCH_CONFIG_INVALID"}),
    ],
)
async def test_update_workbench_config_maps_domain_errors(
    monkeypatch, error, status, detail
):
    monkeypatch.setattr(conversation_app, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(
        conversation_app,
        "get_current_user_id",
        lambda _authorization: ("user-a", "tenant-a"),
    )
    monkeypatch.setattr(
        conversation_app,
        "update_conversation_workbench_config_service",
        MagicMock(side_effect=error),
    )

    with pytest.raises(HTTPException) as caught:
        await conversation_app.update_conversation_workbench_config_endpoint(
            42, _request(), "Bearer token"
        )
    assert caught.value.status_code == status
    assert caught.value.detail == detail


@pytest.mark.asyncio
async def test_update_knowledge_scope_forwards_workbench_version(monkeypatch):
    update = MagicMock(return_value={"knowledge_scope": None})
    monkeypatch.setattr(
        conversation_app,
        "get_current_user_id",
        lambda _authorization: ("user-a", "tenant-a"),
    )
    monkeypatch.setattr(
        conversation_app, "update_conversation_knowledge_scope_service", update
    )
    request = conversation_app.ConversationKnowledgeScopeUpdateRequest(
        scope=None,
        expected_workbench_config_version=3,
    )

    response = await conversation_app.update_conversation_knowledge_scope_endpoint(
        42, request, "Bearer token"
    )

    assert response.data == {"knowledge_scope": None}
    update.assert_called_once_with(
        conversation_id=42,
        knowledge_scope=None,
        user_id="user-a",
        tenant_id="tenant-a",
        expected_workbench_config_version=3,
    )


@pytest.mark.asyncio
async def test_update_knowledge_scope_maps_workbench_conflict(monkeypatch):
    monkeypatch.setattr(
        conversation_app,
        "get_current_user_id",
        lambda _authorization: ("user-a", "tenant-a"),
    )
    monkeypatch.setattr(
        conversation_app,
        "update_conversation_knowledge_scope_service",
        MagicMock(side_effect=conversation_app.WorkbenchConfigVersionConflict(6)),
    )
    request = conversation_app.ConversationKnowledgeScopeUpdateRequest(scope=None)

    with pytest.raises(HTTPException) as caught:
        await conversation_app.update_conversation_knowledge_scope_endpoint(
            42, request, "Bearer token"
        )
    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "WORKBENCH_CONFIG_VERSION_CONFLICT",
        "current_version": 6,
    }
