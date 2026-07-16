"""Tests for structured NL2AGENT API error conversion."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from consts.error_code import ErrorCode
from consts.exceptions import (
    AppException,
    AgentRunException,
    Nl2AgentDraftNotFoundError,
    Nl2AgentExternalServiceError,
    Nl2AgentOperationError,
    Nl2AgentValidationError,
)
from consts.model import Nl2AgentFinalizeRequest, Nl2AgentRecommendationBatchRequest

from apps import nl2agent_app
from apps.nl2agent_app import _session_http_error


def test_session_error_preserves_domain_exception() -> None:
    error = Nl2AgentDraftNotFoundError()

    assert _session_http_error(error) is error


def test_session_error_converts_legacy_workflow_failure_without_message_matching() -> None:
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

    with pytest.raises(AppException) as exc_info:
        await nl2agent_app.start_session_api(MagicMock(), None)

    assert (
        exc_info.value.error_code
        == ErrorCode.AGENTSPACE_NL2AGENT_WORKFLOW_CONFLICT
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

    assert (
        exc_info.value.error_code
        == ErrorCode.AGENTSPACE_NL2AGENT_WORKFLOW_CONFLICT
    )
    register_local.assert_awaited_once_with(
        202,
        "batch",
        [],
        [],
        "tenant",
        "user",
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
