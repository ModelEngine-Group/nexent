"""Tests for structured NL2AGENT API error conversion."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from consts.error_code import ErrorCode
from consts.exceptions import (
    AppException,
    AgentRunException,
    Nl2AgentDraftNotFoundError,
    Nl2AgentExternalServiceError,
    Nl2AgentOperationError,
    Nl2AgentValidationError,
    UnauthorizedError,
)
from consts.model import Nl2AgentFinalizeRequest, Nl2AgentRecommendationBatchRequest

from apps import nl2agent_app
from apps.nl2agent_app import _session_http_error


def test_current_user_maps_authentication_failure_to_http_401(monkeypatch) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "get_current_user_info",
        MagicMock(side_effect=UnauthorizedError("Invalid token")),
    )

    with pytest.raises(nl2agent_app.HTTPException) as exc_info:
        nl2agent_app._current_user(None, MagicMock())

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token"


def test_current_user_does_not_mask_unexpected_auth_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "get_current_user_info",
        MagicMock(side_effect=RuntimeError("auth database unavailable")),
    )

    with pytest.raises(RuntimeError, match="auth database unavailable"):
        nl2agent_app._current_user(None, MagicMock())


@pytest.mark.asyncio
async def test_list_sessions_api_rejects_unauthenticated_request_before_service_call(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "get_current_user_info",
        MagicMock(side_effect=UnauthorizedError("Missing token")),
    )
    list_sessions = MagicMock()
    monkeypatch.setattr(nl2agent_app, "list_active_sessions", list_sessions)

    with pytest.raises(nl2agent_app.HTTPException) as exc_info:
        await nl2agent_app.list_sessions_api(MagicMock(), 25, None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Missing token"
    list_sessions.assert_not_called()


@pytest.mark.asyncio
async def test_list_sessions_http_contract_returns_401_for_missing_auth(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "get_current_user_info",
        MagicMock(side_effect=UnauthorizedError("Missing token")),
    )
    app = FastAPI()
    app.include_router(nl2agent_app.router)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/nl2agent/sessions")

    assert response.status_code == 401
    assert response.json() == {"detail": "Missing token"}


def test_session_error_preserves_domain_exception() -> None:
    error = Nl2AgentDraftNotFoundError()

    assert _session_http_error(error) is error


def test_session_error_converts_legacy_workflow_failure_without_message_matching() -> (
    None
):
    converted = _session_http_error(AgentRunException("A new workflow message."))

    assert converted.error_code == ErrorCode.AGENTSPACE_NL2AGENT_WORKFLOW_CONFLICT
    assert converted.message == "A new workflow message."


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_status"),
    [
        (
            Nl2AgentValidationError("invalid configuration"),
            ErrorCode.AGENTSPACE_NL2AGENT_INVALID_REQUEST,
            400,
        ),
        (
            Nl2AgentExternalServiceError("marketplace unavailable"),
            ErrorCode.AGENTSPACE_NL2AGENT_EXTERNAL_SERVICE_FAILED,
            502,
        ),
        (
            Nl2AgentOperationError("database unavailable"),
            ErrorCode.AGENTSPACE_NL2AGENT_OPERATION_FAILED,
            500,
        ),
    ],
)
def test_session_error_preserves_failure_category(
    error: AgentRunException,
    expected_code: ErrorCode,
    expected_status: int,
) -> None:
    converted = _session_http_error(error)

    assert converted.error_code == expected_code
    assert converted.http_status == expected_status
    assert converted.message == str(error)


def test_session_error_converts_unexpected_failure_to_internal_error() -> None:
    converted = _session_http_error(RuntimeError("database unavailable"))

    assert converted.error_code == ErrorCode.SYSTEM_INTERNAL_ERROR
    assert converted.message == "Failed to load or update NL2AGENT session state."


@pytest.mark.asyncio
async def test_start_session_api_maps_workflow_conflict(monkeypatch) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "get_current_user_info",
        MagicMock(return_value=("user", "tenant", "en")),
    )
    monkeypatch.setattr(
        nl2agent_app,
        "start_session",
        AsyncMock(side_effect=AgentRunException("session conflict")),
    )
    monkeypatch.setattr(
        nl2agent_app,
        "cleanup_expired_sessions",
        MagicMock(return_value=0),
    )

    with pytest.raises(AppException) as exc_info:
        await nl2agent_app.start_session_api(MagicMock(), None)

    assert exc_info.value.error_code == ErrorCode.AGENTSPACE_NL2AGENT_WORKFLOW_CONFLICT


@pytest.mark.asyncio
async def test_resolve_session_api_passes_authenticated_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "_current_user",
        MagicMock(return_value=("user", "tenant", "en")),
    )
    resolve = MagicMock(
        return_value={
            "nl2agent_agent_id": 101,
            "draft_agent_id": 202,
            "conversation_id": 902,
            "status": "active",
        }
    )
    monkeypatch.setattr(nl2agent_app, "resolve_session", resolve)

    result = await nl2agent_app.resolve_session_api(902, MagicMock(), None)

    assert result["draft_agent_id"] == 202
    resolve.assert_called_once_with(
        conversation_id=902,
        tenant_id="tenant",
        user_id="user",
    )


@pytest.mark.asyncio
async def test_resume_session_api_passes_authenticated_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "_current_user",
        MagicMock(return_value=("user", "tenant", "en")),
    )
    resume = MagicMock(
        return_value={
            "nl2agent_agent_id": 101,
            "draft_agent_id": 202,
            "conversation_id": 902,
            "status": "active",
        }
    )
    monkeypatch.setattr(nl2agent_app, "resume_session", resume)

    result = await nl2agent_app.resume_session_api(202, MagicMock(), None)

    assert result["status"] == "active"
    resume.assert_called_once_with(202, "tenant", "user")


@pytest.mark.asyncio
async def test_resolve_session_http_contract_restores_complete_execution_context(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "_current_user",
        MagicMock(return_value=("user", "tenant", "en")),
    )
    monkeypatch.setattr(
        nl2agent_app,
        "resolve_session",
        MagicMock(
            return_value={
                "nl2agent_agent_id": 101,
                "draft_agent_id": 202,
                "conversation_id": 902,
                "status": "active",
            }
        ),
    )
    app = FastAPI()
    app.include_router(nl2agent_app.router)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/nl2agent/session/by-conversation/902")

    assert response.status_code == 200
    assert response.json() == {
        "nl2agent_agent_id": 101,
        "draft_agent_id": 202,
        "conversation_id": 902,
        "status": "active",
    }


@pytest.mark.asyncio
async def test_list_sessions_api_passes_authenticated_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "_current_user",
        MagicMock(return_value=("user", "tenant", "en")),
    )
    list_sessions = MagicMock(return_value=[])
    monkeypatch.setattr(nl2agent_app, "list_active_sessions", list_sessions)

    assert await nl2agent_app.list_sessions_api(MagicMock(), 25, None) == {
        "sessions": []
    }
    list_sessions.assert_called_once_with(
        tenant_id="tenant",
        user_id="user",
        limit=25,
    )


@pytest.mark.asyncio
async def test_abandon_session_api_passes_authenticated_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "_current_user",
        MagicMock(return_value=("user", "tenant", "en")),
    )
    abandon = MagicMock(
        return_value={
            "draft_agent_id": 202,
            "conversation_id": 902,
            "status": "abandoned",
        }
    )
    monkeypatch.setattr(nl2agent_app, "abandon_session", abandon)

    result = await nl2agent_app.abandon_session_api(202, MagicMock(), None)

    assert result["status"] == "abandoned"
    abandon.assert_called_once_with(
        draft_agent_id=202,
        tenant_id="tenant",
        user_id="user",
    )


@pytest.mark.asyncio
async def test_local_registration_api_maps_workflow_conflict(monkeypatch) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "_current_user",
        MagicMock(return_value=("user", "tenant", "en")),
    )
    register_local = AsyncMock(side_effect=AgentRunException("stale card"))
    monkeypatch.setattr(
        nl2agent_app,
        "register_local_resource_recommendations",
        register_local,
    )

    with pytest.raises(AppException) as exc_info:
        await nl2agent_app.register_local_resources_api(
            202,
            Nl2AgentRecommendationBatchRequest(recommendation_batch_id="batch"),
            MagicMock(),
            None,
        )

    assert exc_info.value.error_code == ErrorCode.AGENTSPACE_NL2AGENT_WORKFLOW_CONFLICT
    register_local.assert_awaited_once_with(
        202,
        "batch",
        [],
        [],
        "tenant",
        "user",
    )


@pytest.mark.asyncio
async def test_apply_local_resources_http_contract_accepts_tool_config_map(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "_current_user",
        MagicMock(return_value=("user", "tenant", "en")),
    )
    apply_local = AsyncMock(
        return_value={
            "recommendation_batch_id": "batch",
            "status": "applied",
            "bound_tool_count": 1,
            "bound_skill_count": 0,
            "tool_ids": [28],
            "skill_ids": [],
            "chat_injection_text": "Continue",
        }
    )
    monkeypatch.setattr(nl2agent_app, "apply_local_resources_batch", apply_local)
    app = FastAPI()
    app.include_router(nl2agent_app.router)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/nl2agent/session/202/apply-local-resources",
            json={
                "recommendation_batch_id": "batch",
                "tool_ids": [28],
                "skill_ids": [],
                "tool_config_values": {"28": {"top_k": 8}},
            },
        )

    assert response.status_code == 200
    apply_local.assert_awaited_once_with(
        agent_id=202,
        recommendation_batch_id="batch",
        tool_ids=[28],
        skill_ids=[],
        tool_config_values={28: {"top_k": 8}},
        tenant_id="tenant",
        user_id="user",
    )


@pytest.mark.asyncio
async def test_finalize_api_passes_validated_verification_config(monkeypatch) -> None:
    monkeypatch.setattr(
        nl2agent_app,
        "get_current_user_info",
        MagicMock(return_value=("user", "tenant", "en")),
    )
    finalize = AsyncMock(return_value={"agent_id": 202, "status": "draft_ready"})
    monkeypatch.setattr(nl2agent_app, "finalize_agent", finalize)
    payload = Nl2AgentFinalizeRequest(
        business_description="Build an agent",
        duty_prompt="Help the user",
        greeting_message="Hello",
        verification_config={"enabled": False},
    )

    await nl2agent_app.finalize_agent_api(202, payload, MagicMock(), None)

    verification_config = finalize.await_args.kwargs["verification_config"]
    assert verification_config["enabled"] is False
    assert verification_config["strictness"] == "balanced"
    assert "mode" not in verification_config
