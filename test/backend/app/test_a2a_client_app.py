"""Unit tests for backend.apps.a2a_client_app runtime metadata chat flow."""
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

# =============================================================================
# Stub heavy service / auth modules BEFORE importing the app module, following
# the repository's established sys.modules pattern (see test_agent_db.py).
# The exception classes must be REAL so that `except AgentCallError` clauses
# in the app behave correctly.
# =============================================================================


class _AgentCallError(Exception):
    pass


class _AgentDiscoveryError(Exception):
    pass


client_service_mock = MagicMock()
client_service_mock.a2a_client_service = MagicMock()
client_service_mock.AgentCallError = _AgentCallError
client_service_mock.AgentDiscoveryError = _AgentDiscoveryError
sys.modules["services.a2a_client_service"] = client_service_mock

server_service_mock = MagicMock()
server_service_mock.a2a_server_service = MagicMock()
sys.modules["services.a2a_server_service"] = server_service_mock

sys.modules["database.a2a_agent_db"] = MagicMock()

auth_utils_mock = MagicMock()
auth_utils_mock.get_current_user_info = MagicMock(return_value=("user_1", "tenant_1", None))
sys.modules["utils.auth_utils"] = auth_utils_mock
sys.modules["backend.utils.auth_utils"] = auth_utils_mock

from consts.error_code import RuntimeMetadataValidationCode  # noqa: E402
from consts.exceptions import (  # noqa: E402
    AppException,
    RuntimeMetadataValidationError,
)

from apps.a2a_client_app import router  # noqa: E402

app = FastAPI()
app.include_router(router)

@app.exception_handler(AppException)
async def _app_exception_handler(_request, exc):
    return JSONResponse(
        status_code=exc.http_status,
        content=exc.to_dict(),
    )

client = TestClient(app)

CHAT_URL = "/a2a/client/agents/7/chat"


@pytest.fixture(autouse=True)
def _patch_auth():
    """Stub identity resolution so tests focus on the chat endpoint logic."""
    with patch("apps.a2a_client_app.get_current_user_info", return_value=("user_1", "tenant_1", None)):
        yield


@pytest.fixture(autouse=True)
def _mock_call_agent():
    """Default successful external agent call."""
    with patch(
        "apps.a2a_client_app.a2a_client_service.call_agent",
        new=AsyncMock(return_value={"reply": "hello"}),
    ) as mock_call:
        yield mock_call


def _chat(payload=None, **kwargs):
    return client.post(
        CHAT_URL,
        json={"message": "hello", **(payload or {})},
        **kwargs,
    )


# =============================================================================
# Runtime metadata: validation pass / fail paths
# =============================================================================

def test_chat_without_metadata_omits_metadata_key(_mock_call_agent):
    """metadata=None must skip validation and omit the message metadata key."""
    resp = _chat()
    assert resp.status_code == 200

    called = _mock_call_agent.await_args
    assert called is not None
    message = called.kwargs["message"]
    assert "metadata" not in message
    assert _mock_call_agent.await_args.kwargs["external_agent_id"] == 7
    assert _mock_call_agent.await_args.kwargs["tenant_id"] == "tenant_1"


def test_chat_with_metadata_embeds_metadata(_mock_call_agent):
    """Valid metadata must be embedded into the A2A message and forwarded."""
    metadata = {"session_id": "s-1", "language": "zh"}
    resp = _chat({"metadata": metadata})
    assert resp.status_code == 200
    assert resp.json() == {"status": "success", "data": {"reply": "hello"}}

    message = _mock_call_agent.await_args.kwargs["message"]
    assert message["metadata"] == metadata


def test_chat_metadata_too_large_returns_413(_mock_call_agent):
    """METADATA_TOO_LARGE validation errors map to HTTP 413."""
    with patch(
        "apps.a2a_client_app.validate_runtime_metadata",
        side_effect=RuntimeMetadataValidationError(
            RuntimeMetadataValidationCode.METADATA_TOO_LARGE,
            "too large",
        ),
    ):
        resp = _chat({"metadata": {"big": "x"}})
    assert resp.status_code == 413
    _mock_call_agent.assert_not_awaited()
    assert resp.json()["code"] == "010107"
    assert resp.json()["message"] == "Runtime metadata exceeds the maximum allowed size."
    assert resp.json()["details"] == {"reason": "METADATA_TOO_LARGE"}


def test_chat_metadata_invalid_returns_422(_mock_call_agent):
    """Other validation errors map to HTTP 422."""
    with patch(
        "apps.a2a_client_app.validate_runtime_metadata",
        side_effect=RuntimeMetadataValidationError(
            RuntimeMetadataValidationCode.INVALID_METADATA_TYPE,
            "must be object",
        ),
    ):
        resp = _chat({"metadata": {"invalid": "value"}})
    assert resp.status_code == 422
    _mock_call_agent.assert_not_awaited()
    assert resp.json()["code"] == "010106"
    assert resp.json()["message"] == "Runtime metadata is invalid."
    assert resp.json()["details"] == {"reason": "INVALID_METADATA_TYPE"}


def test_chat_metadata_real_validator_too_large_returns_413(_mock_call_agent):
    """A genuinely oversized payload is rejected by the real validator as 413."""
    oversized = {"payload": "x" * (64 * 1024 + 1)}
    resp = _chat({"metadata": oversized})
    assert resp.status_code == 413
    _mock_call_agent.assert_not_awaited()


def test_chat_metadata_real_validator_invalid_type_returns_422(_mock_call_agent):
    """A non-object metadata payload is rejected by the real validator as 422."""
    resp = _chat({"metadata": ["not", "an", "object"]})
    assert resp.status_code == 422
    _mock_call_agent.assert_not_awaited()


# =============================================================================
# Pre-existing chat flow behavior (regression guards)
# =============================================================================

def test_chat_empty_message_returns_400():
    """Empty or whitespace-only messages must be rejected."""
    resp = _chat({"message": "   "})
    assert resp.status_code == 400


def test_chat_agent_call_error_returns_400():
    """AgentCallError is mapped to HTTP 400."""
    with patch(
        "apps.a2a_client_app.a2a_client_service.call_agent",
        new=AsyncMock(side_effect=_AgentCallError("boom")),
    ):
        resp = _chat()
    assert resp.status_code == 400


def test_chat_agent_discovery_error_returns_404():
    """AgentDiscoveryError is mapped to HTTP 404."""
    with patch(
        "apps.a2a_client_app.a2a_client_service.call_agent",
        new=AsyncMock(side_effect=_AgentDiscoveryError("not found")),
    ):
        resp = _chat()
    assert resp.status_code == 404


def test_chat_generic_error_returns_500():
    """Unexpected errors are mapped to HTTP 500."""
    with patch(
        "apps.a2a_client_app.a2a_client_service.call_agent",
        new=AsyncMock(side_effect=RuntimeError("unexpected")),
    ):
        resp = _chat()
    assert resp.status_code == 500