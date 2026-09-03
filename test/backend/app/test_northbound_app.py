"""Unit tests for backend.apps.northbound_app module."""
import sys
import os

# The conftest.py sets up all mocks

from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from io import BytesIO

# Import from conftest (which sets up mocks automatically)
# Agent management is outside the HTTP boundary exercised in this module.
with pytest.MonkeyPatch.context() as import_mocks:
    import_mocks.setitem(sys.modules, "management.services.agent.service", MagicMock())
    from apps.northbound_app import router
from consts.exceptions import (
    ConversationNotFoundError,
    ForbiddenError,
    LimitExceededError,
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    RuntimeUpstreamError,
    NotFoundException,
    UnauthorizedError,
    SignatureValidationError,
    ValidationError,
)


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def _build_headers(auth="Bearer test_jwt", request_id="req-123", aksk=True):
    """Build request headers for testing."""
    headers = {
        "Authorization": auth,
        "X-Request-Id": request_id,
    }
    if aksk:
        headers.update({
            "X-Access-Key": "ak",
            "X-Timestamp": "1710000000",
            "X-Signature": "sig",
        })
    return headers


# =============================================================================
# Health Check Tests
# =============================================================================

def test_health_check():
    """Test health check endpoint returns healthy status."""
    resp = client.get("/nb/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "northbound-api"


def test_role_for_context_normalizes_database_role():
    with patch("apps.northbound_app.get_user_role_by_tenant", return_value="admin") as mock_role:
        from apps.northbound_app import _role_for_context

        assert _role_for_context("user-1", "tenant-1") == "ADMIN"

    mock_role.assert_called_once_with("user-1", "tenant-1")


@pytest.mark.parametrize(
    ("exception", "expected_status"),
    [
        (ForbiddenError("not allowed"), 403),
        (NotFoundException("missing"), 404),
        (ValidationError("invalid request"), 400),
        (ValueError("invalid value"), 400),
    ],
)
def test_raise_api_key_http_exception_maps_expected_errors(exception, expected_status):
    from apps.northbound_app import _raise_api_key_http_exception

    with pytest.raises(Exception) as raised:
        _raise_api_key_http_exception(exception)

    assert raised.value.status_code == expected_status


def test_raise_api_key_http_exception_reraises_unexpected_error():
    from apps.northbound_app import _raise_api_key_http_exception

    with pytest.raises(RuntimeError, match="database unavailable"):
        _raise_api_key_http_exception(RuntimeError("database unavailable"))


def test_get_northbound_context_logs_non_service_request_usage():
    from starlette.requests import Request
    from apps.northbound_app import _get_northbound_context

    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": "/nb/v1/api-keys",
        "raw_path": b"/nb/v1/api-keys",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer api-key"), (b"x-request-id", b"req-1")],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    })
    with patch("apps.northbound_app.validate_bearer_token", return_value=(True, {"sub": "user-1"})), \
            patch("apps.northbound_app.get_user_and_tenant_by_access_key", return_value={
                "user_id": "user-1", "tenant_id": "tenant-1", "token_id": 9,
            }), \
            patch("apps.northbound_app.log_token_usage") as mock_log:
        context = __import__("asyncio").run(_get_northbound_context(request))

    assert context.request_id == "req-1"
    assert context.authorization == "Bearer api-key"
    mock_log.assert_called_once_with(
        token_id=9,
        call_function_name="/nb/v1/api-keys",
        related_id=None,
        created_by="user-1",
        metadata={"method": "GET", "request_id": "req-1"},
    )


def test_get_northbound_context_skips_usage_log_for_service_logged_paths():
    from starlette.requests import Request
    from apps.northbound_app import _get_northbound_context

    request = Request({
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "path": "/nb/v1/chat/run",
        "raw_path": b"/nb/v1/chat/run",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer api-key")],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    })
    with patch("apps.northbound_app.validate_bearer_token", return_value=(True, {"sub": "user-1"})), \
            patch("apps.northbound_app.get_user_and_tenant_by_access_key", return_value={
                "user_id": "user-1", "tenant_id": "tenant-1", "token_id": 9,
            }), \
            patch("apps.northbound_app.log_token_usage") as mock_log:
        __import__("asyncio").run(_get_northbound_context(request))

    mock_log.assert_not_called()


def test_create_api_users_batch_endpoint_is_exposed_by_northbound_router():
    ctx = MagicMock(user_id="admin-1", tenant_id="tenant-1", request_id="req-123")
    created = [{
        "user_id": "api-user-1",
        "role": "USER",
        "group_id": 1,
        "group_name": "Default",
        "api_key": "nexent-complete-key",
    }]
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app._role_for_context', return_value="ADMIN"), \
            patch('apps.northbound_app.create_api_users_batch', return_value=created) as mock_create:
        mock_ctx.return_value = ctx

        response = client.post(
            "/nb/v1/api-users/batch",
            headers=_build_headers(),
            json={"role": "USER", "count": 1},
        )

    assert response.status_code == 201
    assert response.json()["data"] == created
    mock_create.assert_called_once_with(
        actor_user_id="admin-1",
        actor_tenant_id="tenant-1",
        actor_role="ADMIN",
        role="USER",
        group_id=None,
        count=1,
    )


def test_create_api_users_batch_endpoint_maps_validation_error():
    ctx = MagicMock(user_id="admin-1", tenant_id="tenant-1", request_id="req-123")
    with patch("apps.northbound_app._get_northbound_context", new_callable=AsyncMock) as mock_ctx, \
            patch("apps.northbound_app._role_for_context", return_value="ADMIN"), \
            patch("apps.northbound_app.create_api_users_batch", side_effect=ValidationError("invalid group")):
        mock_ctx.return_value = ctx
        response = client.post(
            "/nb/v1/api-users/batch",
            headers=_build_headers(),
            json={"role": "USER", "count": 1},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid group"


def test_refresh_api_key_endpoint_is_exposed_by_northbound_router():
    ctx = MagicMock(user_id="admin-1", tenant_id="tenant-1", request_id="req-123")
    refreshed = {
        "user_id": "api-user-1",
        "email": None,
        "api_key": "nexent-new-key",
        "revoked_count": 1,
    }
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app._role_for_context', return_value="SU"), \
            patch('apps.northbound_app.refresh_user_api_key', return_value=refreshed):
        mock_ctx.return_value = ctx

        response = client.post(
            "/nb/v1/api-keys/refresh",
            headers=_build_headers(),
            json={"user_id": "api-user-1"},
        )

    assert response.status_code == 200
    assert response.json()["data"] == refreshed


def test_refresh_api_key_endpoint_returns_mapped_forbidden_error():
    ctx = MagicMock(user_id="admin-1", tenant_id="tenant-1", request_id="req-123")
    with patch("apps.northbound_app._get_northbound_context", new_callable=AsyncMock) as mock_ctx, \
            patch("apps.northbound_app._role_for_context", return_value="ADMIN"), \
            patch("apps.northbound_app.refresh_user_api_key", side_effect=ForbiddenError("not allowed")):
        mock_ctx.return_value = ctx
        response = client.post(
            "/nb/v1/api-keys/refresh",
            headers=_build_headers(),
            json={"email": "api.user@example.com"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "not allowed"


def test_revoke_api_key_endpoint_forwards_email_target():
    ctx = MagicMock(user_id="admin-1", tenant_id="tenant-1", request_id="req-123")
    with patch("apps.northbound_app._get_northbound_context", new_callable=AsyncMock) as mock_ctx, \
            patch("apps.northbound_app._role_for_context", return_value="ADMIN"), \
            patch("apps.northbound_app.revoke_user_api_keys", return_value={"revoked_count": 1}) as mock_revoke:
        mock_ctx.return_value = ctx
        response = client.delete(
            "/nb/v1/api-keys?email=api.user@example.com",
            headers=_build_headers(),
        )

    assert response.status_code == 200
    assert response.json()["requestId"] == "req-123"
    mock_revoke.assert_called_once_with(
        actor_user_id="admin-1",
        actor_tenant_id="tenant-1",
        actor_role="ADMIN",
        user_id=None,
        email="api.user@example.com",
    )


def test_revoke_api_key_endpoint_rejects_missing_target():
    ctx = MagicMock(user_id="admin-1", tenant_id="tenant-1", request_id="req-123")
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx:
        mock_ctx.return_value = ctx
        response = client.delete("/nb/v1/api-keys", headers=_build_headers())

    assert response.status_code == 400


# =============================================================================
# Upload Chat Attachments Tests
# =============================================================================

def test_upload_chat_attachments_success():
    """Test successful chat attachment upload."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.upload_files_for_northbound', new_callable=AsyncMock) as mock_upload:

        mock_ctx.return_value = MagicMock()
        mock_upload.return_value = {
            "message": "Processed 1 files",
            "requestId": "req-123",
            "results": [{"filename": "test.pdf", "status": "success"}],
        }

        # Create a fake file upload
        file_content = b"test file content"
        files = {"files": ("test.pdf", BytesIO(file_content), "application/pdf")}

        resp = client.post(
            "/nb/v1/chat/attachments/upload",
            files=files,
            headers=_build_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Processed 1 files"


def test_upload_chat_attachments_limit_exceeded():
    """Test upload returns 429 when limit exceeded."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.upload_files_for_northbound', new_callable=AsyncMock) as mock_upload:

        mock_ctx.return_value = MagicMock()
        mock_upload.side_effect = LimitExceededError("Upload limit exceeded")

        file_content = b"test file content"
        files = {"files": ("test.pdf", BytesIO(file_content), "application/pdf")}

        resp = client.post(
            "/nb/v1/chat/attachments/upload",
            files=files,
            headers=_build_headers(),
        )

        assert resp.status_code == 429


def test_upload_chat_attachments_internal_error():
    """Test upload returns 500 when internal error occurs."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.upload_files_for_northbound', new_callable=AsyncMock) as mock_upload:

        mock_ctx.return_value = MagicMock()
        mock_upload.side_effect = Exception("Unknown error")

        file_content = b"test file content"
        files = {"files": ("test.pdf", BytesIO(file_content), "application/pdf")}

        resp = client.post(
            "/nb/v1/chat/attachments/upload",
            files=files,
            headers=_build_headers(),
        )

        assert resp.status_code == 500


# =============================================================================
# Run Chat Tests
# =============================================================================

def test_run_chat_success():
    """Test successful chat run initiation."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.return_value = {
            "message": "Chat run initiated",
            "request_id": "req-789",
            "status": "initiated",
        }

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Hello, agent",
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 200


def test_run_chat_limit_exceeded():
    """Test run chat returns 429 when limit exceeded."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.side_effect = LimitExceededError("Rate limit exceeded")

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Hello",
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 429


def test_run_chat_unauthorized():
    """Test run chat returns 500 on unauthorized (broad exception handling)."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx:
        mock_ctx.side_effect = UnauthorizedError("Invalid token")

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Hello",
            },
            headers=_build_headers(),
        )

        # The run_chat endpoint has broad exception handling, so unauthorized returns 500
        assert resp.status_code == 500


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (RuntimeServiceUnavailableError("unavailable"), 502),
        (RuntimeServiceTimeoutError("timed out"), 504),
    ],
)
def test_run_chat_maps_runtime_transport_errors(error, expected_status):
    with patch(
        "apps.northbound_app._get_northbound_context",
        new_callable=AsyncMock,
    ) as mock_ctx, patch(
        "apps.northbound_app.start_streaming_chat",
        new_callable=AsyncMock,
        side_effect=error,
    ):
        mock_ctx.return_value = MagicMock()

        response = client.post(
            "/nb/v1/chat/run",
            json={"agent_name": "general-assistant", "query": "Hello"},
            headers=_build_headers(),
        )

    assert response.status_code == expected_status


# =============================================================================
# Stop Chat Tests
# =============================================================================

def test_stop_chat_success():
    """Test successful chat stop."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.stop_chat', new_callable=AsyncMock) as mock_stop:

        mock_ctx.return_value = MagicMock()
        mock_stop.return_value = True

        resp = client.get(
            "/nb/v1/chat/stop/123",
            headers=_build_headers(),
        )

        assert resp.status_code == 200


def test_stop_chat_preserves_runtime_error_response():
    upstream_error = RuntimeUpstreamError(
        status_code=403,
        content=b'{"message":"forbidden"}',
        headers={"content-type": "application/json"},
    )
    with patch(
        "apps.northbound_app._get_northbound_context",
        new_callable=AsyncMock,
    ) as mock_ctx, patch(
        "apps.northbound_app.stop_chat",
        new_callable=AsyncMock,
        side_effect=upstream_error,
    ):
        mock_ctx.return_value = MagicMock()

        response = client.get(
            "/nb/v1/chat/stop/123",
            headers=_build_headers(),
        )

    assert response.status_code == 403
    assert response.json() == {"message": "forbidden"}


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (RuntimeServiceUnavailableError("unavailable"), 502),
        (RuntimeServiceTimeoutError("timed out"), 504),
    ],
)
def test_stop_chat_maps_runtime_transport_errors(error, expected_status):
    with patch(
        "apps.northbound_app._get_northbound_context",
        new_callable=AsyncMock,
    ) as mock_ctx, patch(
        "apps.northbound_app.stop_chat",
        new_callable=AsyncMock,
        side_effect=error,
    ):
        mock_ctx.return_value = MagicMock()

        response = client.get(
            "/nb/v1/chat/stop/123",
            headers=_build_headers(),
        )

    assert response.status_code == expected_status


# =============================================================================
# Get Conversation Tests
# =============================================================================

def test_get_conversation_success():
    """Test successful retrieval of conversation."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_conversation_history', new_callable=AsyncMock) as mock_get:

        mock_ctx.return_value = MagicMock()
        mock_get.return_value = {
            "conversation_id": 123,
            "history": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ]
        }

        resp = client.get(
            "/nb/v1/conversations/123",
            headers=_build_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_id"] == 123
        assert len(data["history"]) == 2


# =============================================================================
# List Agents Tests
# =============================================================================

def test_list_agents_success():
    """Test successful retrieval of agent list."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_info_list', new_callable=AsyncMock) as mock_get:

        mock_ctx.return_value = MagicMock()
        mock_get.return_value = {
            "agents": [
                {"name": "agent1", "description": "First agent"},
                {"name": "agent2", "description": "Second agent"},
            ]
        }

        resp = client.get(
            "/nb/v1/agents",
            headers=_build_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["agents"]) == 2


def test_get_agent_by_name_success():
    """Test successful retrieval of one published agent by name."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_info_by_name_for_northbound', new_callable=AsyncMock) as mock_get:

        mock_ctx.return_value = MagicMock()
        mock_get.return_value = {
            "message": "success",
            "data": {"name": "agent1", "description": "First agent"},
            "requestId": "req-123",
        }

        resp = client.get(
            "/nb/v1/agents/agent1",
            headers=_build_headers(),
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "agent1"
        mock_get.assert_awaited_once()


def test_get_agent_by_name_not_found():
    """Test missing published agent returns 404."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_info_by_name_for_northbound', new_callable=AsyncMock) as mock_get:

        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = LookupError("Published agent not found: missing-agent")

        resp = client.get(
            "/nb/v1/agents/missing-agent",
            headers=_build_headers(),
        )

        assert resp.status_code == 404
        assert "missing-agent" in resp.json()["detail"]


def test_get_agent_by_name_limit_exceeded():
    """Test get agent by name returns 429 when limit exceeded."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_info_by_name_for_northbound', new_callable=AsyncMock) as mock_get:

        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = LimitExceededError("Rate limit exceeded")

        resp = client.get(
            "/nb/v1/agents/any-agent",
            headers=_build_headers(),
        )

        assert resp.status_code == 429


def test_get_agent_by_name_internal_error():
    """Test get agent by name returns 500 on unexpected internal error."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_info_by_name_for_northbound', new_callable=AsyncMock) as mock_get:

        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = Exception("Unexpected internal error")

        resp = client.get(
            "/nb/v1/agents/any-agent",
            headers=_build_headers(),
        )

        assert resp.status_code == 500


def test_get_agent_knowledge_bases_success():
    """Test user-visible knowledge bases are returned for a published agent."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_knowledge_bases_for_northbound', new_callable=AsyncMock) as mock_get:
        mock_ctx.return_value = MagicMock()
        mock_get.return_value = {
            "message": "success",
            "data": {
                "source": "aidp",
                "tool_name": "AidpSearchTool",
                "range_parameter": "kds_list",
                "knowledge_bases": [{"id": "kds-1", "name": "Policies"}],
            },
            "requestId": "req-123",
        }

        resp = client.get(
            "/nb/v1/agents/agent1/knowledge-bases",
            headers=_build_headers(),
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["range_parameter"] == "kds_list"
        mock_get.assert_awaited_once()


def test_get_agent_knowledge_bases_source_conflict():
    """Test agents with both knowledge sources return a configuration conflict."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_knowledge_bases_for_northbound', new_callable=AsyncMock) as mock_get:
        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = ValueError(
            "The agent enables both local and AIDP knowledge retrieval."
        )

        resp = client.get(
            "/nb/v1/agents/agent1/knowledge-bases",
            headers=_build_headers(),
        )

        assert resp.status_code == 409


# =============================================================================
# List Conversations Tests
# =============================================================================

def test_list_conversations_success():
    """Test successful retrieval of conversation list."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.list_conversations', new_callable=AsyncMock) as mock_list:

        mock_ctx.return_value = MagicMock()
        mock_list.return_value = {
            "conversations": [
                {"id": 1, "title": "Conversation 1"},
                {"id": 2, "title": "Conversation 2"},
            ]
        }

        resp = client.get(
            "/nb/v1/conversations",
            headers=_build_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["conversations"]) == 2


# =============================================================================
# Update Conversation Title Tests
# =============================================================================

def test_update_conversation_title_success():
    """Test successful update of conversation title."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.update_conversation_title', new_callable=AsyncMock) as mock_update:

        mock_ctx.return_value = MagicMock()
        mock_ctx.return_value.request_id = "req-123"
        mock_update.return_value = {"idempotency_key": "idem-key", "conversation_id": 123, "title": "New Title"}

        resp = client.put(
            "/nb/v1/conversations/123/title?title=New%20Title",
            headers=_build_headers(),
        )

        assert resp.status_code == 200


# =============================================================================
# Model List and Generated Title Tests
# =============================================================================

def test_list_configured_models_success():
    ctx = MagicMock(tenant_id="tenant-1", request_id="req-123")
    models = [{"model_id": 7, "display_name": "Main model"}]
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.list_configured_models', new_callable=AsyncMock) as mock_list:
        mock_ctx.return_value = ctx
        mock_list.return_value = {
            "message": "success",
            "data": models,
            "requestId": "req-123",
        }

        resp = client.get("/nb/v1/models", headers=_build_headers())

    assert resp.status_code == 200
    assert resp.json()["data"] == models
    mock_list.assert_awaited_once_with(ctx=ctx)


def test_generate_title_success():
    ctx = MagicMock(user_id="user-1", tenant_id="tenant-1", request_id="req-123")
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_user_language', return_value="en"), \
            patch('apps.northbound_app.generate_conversation_title', new_callable=AsyncMock) as mock_generate:
        mock_ctx.return_value = ctx
        mock_generate.return_value = {
            "message": "success",
            "data": "Generated title",
            "requestId": "req-123",
        }

        resp = client.post(
            "/nb/v1/generate_title",
            headers=_build_headers(),
            json={"conversation_id": 42, "question": "Summarize this conversation"},
        )

    assert resp.status_code == 200
    assert resp.json()["data"] == "Generated title"
    mock_generate.assert_awaited_once_with(
        ctx=ctx,
        conversation_id=42,
        question="Summarize this conversation",
        language="en",
    )


# =============================================================================
# File Fetch Tests
# =============================================================================

def test_file_fetch_missing_url():
    """Test file fetch returns 422 when URL is missing."""
    resp = client.get(
        "/nb/v1/file/fetch",
        headers=_build_headers(),
    )

    # Missing required parameter returns 422
    assert resp.status_code == 422


# =============================================================================
# Error Handling Tests
# =============================================================================

def test_invalid_request_body():
    """Test that invalid request body returns 422."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx:
        mock_ctx.return_value = MagicMock()

        resp = client.post(
            "/nb/v1/chat/run",
            json={},  # Missing required fields
            headers=_build_headers(),
        )

        # FastAPI returns 422 for validation errors
        assert resp.status_code == 422


def test_run_chat_with_conversation_id():
    """Test run chat with existing conversation ID."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.return_value = {
            "message": "Chat run continued",
            "request_id": "req-456",
            "status": "continued",
        }

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Hello again",
                "conversation_id": 123,
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 200


def test_run_chat_with_attachments():
    """Test run chat with file attachments."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.return_value = {
            "message": "Chat run with attachments",
            "request_id": "req-789",
            "status": "initiated",
        }

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Summarize the attached report",
                "attachments": ["s3://nexent/attachments/file.pdf"],
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 200


def test_run_chat_with_tool_params():
    """Test run chat with tool parameter overrides."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.return_value = {
            "message": "Chat run with tool params",
            "request_id": "req-101",
            "status": "initiated",
        }

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Search the knowledge base",
                "tool_params": {
                    "agents": {
                        "general-assistant": {
                            "tools": {
                                "knowledge_base_search": {
                                    "top_k": 5,
                                }
                            }
                        }
                    }
                },
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 200


def test_run_chat_with_model_id():
    """Test run chat with a custom model_id to override the agent's default model."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.return_value = MagicMock()

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Hello with custom model",
                "model_id": 123,
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 200
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["model_id"] == 123


def test_run_chat_with_model_id_and_attachments():
    """Test run chat with both model_id override and file attachments."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.return_value = MagicMock()

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Summarize with custom model",
                "attachments": ["s3://nexent/attachments/file.pdf"],
                "model_id": 456,
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 200
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["model_id"] == 456
        assert kwargs["attachments"] == ["s3://nexent/attachments/file.pdf"]


def test_run_chat_with_model_id_and_tool_params():
    """Test run chat with model_id override combined with tool parameter overrides."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.return_value = MagicMock()

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Search with custom model",
                "model_id": 789,
                "tool_params": {
                    "agents": {
                        "general-assistant": {
                            "tools": {
                                "knowledge_base_search": {
                                    "top_k": 10,
                                }
                            }
                        }
                    }
                },
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 200
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["model_id"] == 789
        assert kwargs["tool_params"] is not None


def test_run_chat_with_model_id_and_conversation_id():
    """Test run chat with model_id override and existing conversation."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.return_value = MagicMock()

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Continue conversation with custom model",
                "conversation_id": 999,
                "model_id": 321,
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 200
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["model_id"] == 321
        assert kwargs["conversation_id"] == 999


def test_run_chat_model_id_null_uses_agent_default():
    """Test that omitting model_id (null) preserves the agent's default model behavior."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.return_value = MagicMock()

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Hello without model_id",
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 200
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["model_id"] is None


def test_run_chat_permission_error():
    """Test run chat returns 403 when permission denied."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.side_effect = PermissionError("Access denied")

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Hello",
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 403


def test_run_chat_internal_error():
    """Test run chat returns 500 on internal error."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.side_effect = Exception("Unexpected error")

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Hello",
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 500


def test_run_chat_value_error():
    """Test run chat returns 400 on value error."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:

        mock_ctx.return_value = MagicMock()
        mock_run.side_effect = ValueError("Invalid agent name")

        resp = client.post(
            "/nb/v1/chat/run",
            json={
                "agent_name": "general-assistant",
                "query": "Hello",
            },
            headers=_build_headers(),
        )

        assert resp.status_code == 400


# =============================================================================
# Stop Chat Error Tests
# =============================================================================

def test_stop_chat_limit_exceeded():
    """Test stop chat returns 429 when limit exceeded."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.stop_chat', new_callable=AsyncMock) as mock_stop:

        mock_ctx.return_value = MagicMock()
        mock_stop.side_effect = LimitExceededError("Rate limit exceeded")

        resp = client.get(
            "/nb/v1/chat/stop/123",
            headers=_build_headers(),
        )

        assert resp.status_code == 429


def test_stop_chat_internal_error():
    """Test stop chat returns 500 on internal error."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.stop_chat', new_callable=AsyncMock) as mock_stop:

        mock_ctx.return_value = MagicMock()
        mock_stop.side_effect = Exception("Unexpected error")

        resp = client.get(
            "/nb/v1/chat/stop/123",
            headers=_build_headers(),
        )

        assert resp.status_code == 500


# =============================================================================
# Get Conversation Error Tests
# =============================================================================

def test_get_conversation_limit_exceeded():
    """Test get conversation returns 429 when limit exceeded."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_conversation_history', new_callable=AsyncMock) as mock_get:

        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = LimitExceededError("Rate limit exceeded")

        resp = client.get(
            "/nb/v1/conversations/123",
            headers=_build_headers(),
        )

        assert resp.status_code == 429


def test_get_conversation_internal_error():
    """Test get conversation returns 500 on internal error."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_conversation_history', new_callable=AsyncMock) as mock_get:

        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = Exception("Unexpected error")

        resp = client.get(
            "/nb/v1/conversations/123",
            headers=_build_headers(),
        )

        assert resp.status_code == 500


# =============================================================================
# List Agents Error Tests
# =============================================================================

def test_list_agents_limit_exceeded():
    """Test list agents returns 429 when limit exceeded."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_info_list', new_callable=AsyncMock) as mock_get:

        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = LimitExceededError("Rate limit exceeded")

        resp = client.get(
            "/nb/v1/agents",
            headers=_build_headers(),
        )

        assert resp.status_code == 429


def test_list_agents_internal_error():
    """Test list agents returns 500 on internal error."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_info_list', new_callable=AsyncMock) as mock_get:

        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = Exception("Unexpected error")

        resp = client.get(
            "/nb/v1/agents",
            headers=_build_headers(),
        )

        assert resp.status_code == 500


# =============================================================================
# List Conversations Error Tests
# =============================================================================

def test_list_conversations_limit_exceeded():
    """Test list conversations returns 429 when limit exceeded."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.list_conversations', new_callable=AsyncMock) as mock_list:

        mock_ctx.return_value = MagicMock()
        mock_list.side_effect = LimitExceededError("Rate limit exceeded")

        resp = client.get(
            "/nb/v1/conversations",
            headers=_build_headers(),
        )

        assert resp.status_code == 429


def test_list_conversations_internal_error():
    """Test list conversations returns 500 on internal error."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.list_conversations', new_callable=AsyncMock) as mock_list:

        mock_ctx.return_value = MagicMock()
        mock_list.side_effect = Exception("Unexpected error")

        resp = client.get(
            "/nb/v1/conversations",
            headers=_build_headers(),
        )

        assert resp.status_code == 500


# =============================================================================
# Update Conversation Title Error Tests
# =============================================================================

def test_update_conversation_title_limit_exceeded():
    """Test update conversation title returns 429 when limit exceeded."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.update_conversation_title', new_callable=AsyncMock) as mock_update:

        mock_ctx.return_value = MagicMock()
        mock_ctx.return_value.request_id = "req-123"
        mock_update.side_effect = LimitExceededError("Rate limit exceeded")

        resp = client.put(
            "/nb/v1/conversations/123/title?title=New%20Title",
            headers=_build_headers(),
        )

        assert resp.status_code == 429


def test_update_conversation_title_not_found():
    """Test update conversation title returns 404 when conversation not found."""
    from consts.exceptions import ConversationNotFoundError

    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.update_conversation_title', new_callable=AsyncMock) as mock_update:

        mock_ctx.return_value = MagicMock()
        mock_ctx.return_value.request_id = "req-123"
        mock_update.side_effect = ConversationNotFoundError("Conversation not found")

        resp = client.put(
            "/nb/v1/conversations/999/title?title=New%20Title",
            headers=_build_headers(),
        )

        assert resp.status_code == 404


def test_update_conversation_title_internal_error():
    """Test update conversation title returns 500 on internal error."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.update_conversation_title', new_callable=AsyncMock) as mock_update:

        mock_ctx.return_value = MagicMock()
        mock_ctx.return_value.request_id = "req-123"
        mock_update.side_effect = Exception("Unexpected error")

        resp = client.put(
            "/nb/v1/conversations/123/title?title=New%20Title",
            headers=_build_headers(),
        )

        assert resp.status_code == 500


def test_update_conversation_title_with_meta_data():
    """Test update conversation title with metadata."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.update_conversation_title', new_callable=AsyncMock) as mock_update:

        mock_ctx.return_value = MagicMock()
        mock_ctx.return_value.request_id = "req-123"
        mock_update.return_value = {"idempotency_key": "idem-key", "conversation_id": 123}

        resp = client.put(
            "/nb/v1/conversations/123/title?title=New%20Title&meta_data=%7B%22source%22%3A%22test%22%7D",
            headers=_build_headers(),
        )

        assert resp.status_code == 200


def test_update_conversation_title_with_idempotency_key():
    """Test update conversation title with idempotency key."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.update_conversation_title', new_callable=AsyncMock) as mock_update:

        mock_ctx.return_value = MagicMock()
        mock_ctx.return_value.request_id = "req-123"
        mock_update.return_value = {"idempotency_key": "my-key", "conversation_id": 123}

        resp = client.put(
            "/nb/v1/conversations/123/title?title=New%20Title",
            headers={**_build_headers(), "Idempotency-Key": "my-key"},
        )

        assert resp.status_code == 200


# =============================================================================
# Upload Attachments Error Tests
# =============================================================================

def test_upload_chat_attachments_value_error():
    """Test upload returns 400 on value error."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.upload_files_for_northbound', new_callable=AsyncMock) as mock_upload:

        mock_ctx.return_value = MagicMock()
        mock_upload.side_effect = ValueError("Invalid file")

        file_content = b"test file content"
        files = {"files": ("test.pdf", BytesIO(file_content), "application/pdf")}

        resp = client.post(
            "/nb/v1/chat/attachments/upload",
            files=files,
            headers=_build_headers(),
        )

        assert resp.status_code == 400


def test_upload_chat_attachments_permission_error():
    """Test upload returns 403 on permission error."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.upload_files_for_northbound', new_callable=AsyncMock) as mock_upload:

        mock_ctx.return_value = MagicMock()
        mock_upload.side_effect = PermissionError("Access denied")

        file_content = b"test file content"
        files = {"files": ("test.pdf", BytesIO(file_content), "application/pdf")}

        resp = client.post(
            "/nb/v1/chat/attachments/upload",
            files=files,
            headers=_build_headers(),
        )

        assert resp.status_code == 403


# =============================================================================
# Additional Branch Coverage Tests
# =============================================================================


def _request(path="/nb/v1/agents", method="GET", headers=None):
    from starlette.requests import Request

    request_headers = [(b"authorization", b"Bearer api-key")]
    for key, value in (headers or {}).items():
        request_headers.append((key.lower().encode(), value.encode()))
    return Request({
        "type": "http",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": request_headers,
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    })


@pytest.mark.parametrize(
    ("token_result", "lookup_result", "expected_status", "detail"),
    [
        ((False, None), None, 401, "Invalid or missing bearer token"),
        ((True, {"sub": "user"}), {"tenant_id": "tenant"}, 400, "Missing user information"),
        ((True, {"sub": "user"}), {"user_id": "user"}, 400, "Missing tenant information"),
    ],
)
def test_get_northbound_context_rejects_invalid_identity(
    token_result, lookup_result, expected_status, detail
):
    from apps.northbound_app import _get_northbound_context

    with patch("apps.northbound_app.validate_bearer_token", return_value=token_result), \
            patch("apps.northbound_app.get_user_and_tenant_by_access_key", return_value=lookup_result):
        with pytest.raises(Exception) as raised:
            __import__("asyncio").run(_get_northbound_context(_request()))

    assert raised.value.status_code == expected_status
    assert detail in raised.value.detail


@pytest.mark.parametrize(
    "error",
    [LimitExceededError("limited"), UnauthorizedError("unauthorized"), RuntimeError("broken")],
)
def test_get_northbound_context_maps_authentication_errors(error):
    from apps.northbound_app import _get_northbound_context

    with patch("apps.northbound_app.validate_bearer_token", side_effect=error):
        with pytest.raises(Exception) as raised:
            __import__("asyncio").run(_get_northbound_context(_request()))

    assert raised.value.status_code in (401, 429)


def test_get_northbound_context_generates_request_id_and_survives_usage_log_failure():
    from apps.northbound_app import _get_northbound_context

    with patch("apps.northbound_app.validate_bearer_token", return_value=(True, {"sub": "user"})), \
            patch("apps.northbound_app.get_user_and_tenant_by_access_key", return_value={
                "user_id": "user", "tenant_id": "tenant", "token_id": 2,
            }), patch("apps.northbound_app.log_token_usage", side_effect=RuntimeError("db")):
        context = __import__("asyncio").run(_get_northbound_context(_request()))

    assert context.request_id
    assert context.authorization == "Bearer api-key"


def test_get_northbound_context_does_not_log_non_positive_token_id():
    from apps.northbound_app import _get_northbound_context

    with patch("apps.northbound_app.validate_bearer_token", return_value=(True, {"sub": "user"})), \
            patch("apps.northbound_app.get_user_and_tenant_by_access_key", return_value={
                "user_id": "user", "tenant_id": "tenant", "token_id": 0,
            }), patch("apps.northbound_app.log_token_usage") as mock_log:
        __import__("asyncio").run(_get_northbound_context(_request()))

    mock_log.assert_not_called()


@pytest.mark.parametrize(
    ("endpoint", "service_name", "error", "expected_status"),
    [
        ("/nb/v1/models", "list_configured_models", RuntimeError("failed"), 500),
        ("/nb/v1/generate_title", "generate_conversation_title", NotFoundException("missing"), 404),
        ("/nb/v1/generate_title", "generate_conversation_title", RuntimeError("failed"), 500),
    ],
)
def test_simple_northbound_endpoints_map_errors(endpoint, service_name, error, expected_status):
    payload = {"conversation_id": 1, "question": "question"} if "generate_title" in endpoint else None
    request_method = client.post if payload else client.get
    with patch("apps.northbound_app._get_northbound_context", new_callable=AsyncMock) as mock_ctx, \
            patch(f"apps.northbound_app.{service_name}", new_callable=AsyncMock, side_effect=error), \
            patch("apps.northbound_app.get_user_language", return_value="en"):
        mock_ctx.return_value = MagicMock()
        response = request_method(endpoint, headers=_build_headers(), json=payload) if payload else request_method(
            endpoint, headers=_build_headers()
        )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("service_name", "error", "expected_status"),
    [
        ("get_conversation_history", LimitExceededError("limited"), 429),
        ("get_conversation_history", RuntimeError("failed"), 500),
        ("get_agent_info_list", LimitExceededError("limited"), 429),
        ("get_agent_info_list", RuntimeError("failed"), 500),
        ("get_agent_info_by_name_for_northbound", ValueError("invalid"), 400),
        ("get_agent_info_by_name_for_northbound", HTTPException(status_code=418, detail="teapot"), 418),
        ("list_conversations", LimitExceededError("limited"), 429),
        ("list_conversations", RuntimeError("failed"), 500),
    ],
)
def test_northbound_endpoint_error_mappings(service_name, error, expected_status):
    from fastapi import HTTPException

    path_by_service = {
        "get_conversation_history": "/nb/v1/conversations/1",
        "get_agent_info_list": "/nb/v1/agents",
        "get_agent_info_by_name_for_northbound": "/nb/v1/agents/agent",
        "list_conversations": "/nb/v1/conversations",
    }
    with patch("apps.northbound_app._get_northbound_context", new_callable=AsyncMock) as mock_ctx, \
            patch(f"apps.northbound_app.{service_name}", new_callable=AsyncMock, side_effect=error):
        mock_ctx.return_value = MagicMock()
        response = client.get(path_by_service[service_name], headers=_build_headers())

    assert response.status_code == expected_status


def test_update_conversation_title_ignores_invalid_metadata_and_sets_headers():
    with patch("apps.northbound_app._get_northbound_context", new_callable=AsyncMock) as mock_ctx, \
            patch("apps.northbound_app.update_conversation_title", new_callable=AsyncMock) as mock_update:
        mock_ctx.return_value = MagicMock(request_id="req-1")
        mock_update.return_value = {"idempotency_key": "generated", "title": "New"}
        response = client.put(
            "/nb/v1/conversations/1/title?title=New&meta_data=invalid",
            headers={**_build_headers(), "Idempotency-Key": "input"},
        )

    assert response.status_code == 200
    assert response.headers["Idempotency-Key"] == "generated"
    assert response.headers["X-Request-Id"] == "req-1"
    assert mock_update.await_args.kwargs["meta_data"] is None


@pytest.mark.parametrize(
    ("service_name", "error", "expected_status"),
    [
        ("list_configured_models", HTTPException(status_code=401, detail="unauthorized"), 401),
        ("generate_conversation_title", ConversationNotFoundError("missing"), 404),
    ],
)
def test_models_and_title_preserve_expected_http_errors(service_name, error, expected_status):
    from fastapi import HTTPException

    path = "/nb/v1/models" if service_name == "list_configured_models" else "/nb/v1/generate_title"
    with patch("apps.northbound_app._get_northbound_context", new_callable=AsyncMock) as mock_ctx, \
            patch(f"apps.northbound_app.{service_name}", new_callable=AsyncMock, side_effect=error), \
            patch("apps.northbound_app.get_user_language", return_value="en"):
        mock_ctx.return_value = MagicMock()
        response = client.get(path, headers=_build_headers()) if path.endswith("models") else client.post(
            path, headers=_build_headers(), json={"conversation_id": 1, "question": "q"}
        )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("url", "expected_status"),
    [("ftp://example.com/file.txt", 400), ("not a url", 400), ("", 400)],
)
def test_file_fetch_rejects_invalid_urls(url, expected_status):
    response = client.get("/nb/v1/file/fetch", params={"presigned_url": url})
    assert response.status_code == expected_status


def test_file_fetch_returns_bad_gateway_for_storage_status():
    response = MagicMock(status_code=404)
    response.headers = {}
    with patch("apps.northbound_app.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__ = AsyncMock(return_value=client_cls.return_value)
        client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value.get = AsyncMock(return_value=response)
        result = client.get("/nb/v1/file/fetch", params={"presigned_url": "https://storage/file"})

    assert result.status_code == 502


@pytest.mark.parametrize("error", [httpx.TimeoutException("timeout"), httpx.RequestError("request failed")])
def test_file_fetch_maps_http_client_errors(error):
    with patch("apps.northbound_app.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__ = AsyncMock(return_value=client_cls.return_value)
        client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value.get = AsyncMock(side_effect=error)
        result = client.get("/nb/v1/file/fetch", params={"presigned_url": "https://storage/file"})

    assert result.status_code == (504 if isinstance(error, httpx.TimeoutException) else 502)


def test_file_fetch_streams_content_and_uses_content_disposition_filename():
    async def chunks():
        yield b"file content"

    response = MagicMock(status_code=200)
    response.headers = {
        "Content-Type": "text/plain",
        "Content-Disposition": 'attachment; filename="report.txt"',
    }
    response.aiter_bytes = chunks
    with patch("apps.northbound_app.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__ = AsyncMock(return_value=client_cls.return_value)
        client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value.get = AsyncMock(return_value=response)
        result = client.get("/nb/v1/file/fetch", params={"presigned_url": "https://storage/file"})

    assert result.status_code == 200
    assert result.content == b"file content"
    assert "report.txt" in result.headers["content-disposition"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# =============================================================================
# Helper Function Tests
# =============================================================================

def test_resolve_proxy_download_filename_with_rfc598_filename():
    """Test filename resolution with RFC 598 filename."""
    from apps.northbound_app import _resolve_proxy_download_filename

    result = _resolve_proxy_download_filename(
        "https://example.com/path/file.pdf",
        'filename="report.pdf"'
    )
    assert result == "report.pdf"


def test_resolve_proxy_download_filename_with_rfc598_star_filename():
    """Test filename resolution with RFC 598 star filename."""
    from apps.northbound_app import _resolve_proxy_download_filename

    result = _resolve_proxy_download_filename(
        "https://example.com/path/file.pdf",
        "filename*=UTF-8''report%20final.pdf"
    )
    assert result == "report final.pdf"


def test_resolve_proxy_download_filename_from_url():
    """Test filename resolution from URL when no content-disposition."""
    from apps.northbound_app import _resolve_proxy_download_filename

    result = _resolve_proxy_download_filename(
        "https://example.com/path/to/document.pdf",
        ""
    )
    assert result == "document.pdf"


def test_resolve_proxy_download_filename_no_filename_in_url():
    """Test filename resolution returns 'download' when no filename in URL."""
    from apps.northbound_app import _resolve_proxy_download_filename

    result = _resolve_proxy_download_filename(
        "https://example.com/path/",
        ""
    )
    assert result == "download"


def test_resolve_proxy_download_filename_empty_content_disposition():
    """Test filename resolution with empty content-disposition."""
    from apps.northbound_app import _resolve_proxy_download_filename

    result = _resolve_proxy_download_filename(
        "https://example.com/path/file.pdf",
        None
    )
    assert result == "file.pdf"

def test_get_agent_knowledge_bases_not_found():
    """Test 404 when the target agent cannot be found."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_knowledge_bases_for_northbound', new_callable=AsyncMock) as mock_get:
        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = LookupError("agent not found")

        resp = client.get(
            "/nb/v1/agents/missing/knowledge-bases",
            headers=_build_headers(),
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "agent not found"


def test_get_agent_knowledge_bases_limit_exceeded():
    """Test 429 when the northbound quota is exceeded."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_knowledge_bases_for_northbound', new_callable=AsyncMock) as mock_get:
        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = LimitExceededError("Rate limit exceeded")

        resp = client.get(
            "/nb/v1/agents/agent1/knowledge-bases",
            headers=_build_headers(),
        )

        assert resp.status_code == 429


def test_get_agent_knowledge_bases_internal_error():
    """Test 500 when an unexpected error occurs."""
    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.get_agent_knowledge_bases_for_northbound', new_callable=AsyncMock) as mock_get:
        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = RuntimeError("boom")

        resp = client.get(
            "/nb/v1/agents/agent1/knowledge-bases",
            headers=_build_headers(),
        )

        assert resp.status_code == 500


def test_get_agent_knowledge_bases_http_exception_passthrough():
    """HTTPException raised earlier in the call chain is re-raised unchanged."""
    from fastapi import HTTPException

    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx,             patch('apps.northbound_app.get_agent_knowledge_bases_for_northbound', new_callable=AsyncMock) as mock_get:
        mock_ctx.return_value = MagicMock()
        mock_get.side_effect = HTTPException(status_code=403, detail="forbidden")

        resp = client.get(
            "/nb/v1/agents/agent1/knowledge-bases",
            headers=_build_headers(),
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == "forbidden"
