"""Unit tests for backend.apps.northbound_app module."""
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

# The conftest.py sets up all mocks

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

# Import from conftest (which sets up mocks automatically)
from apps.northbound_app import _get_northbound_context, router
from apps.app_factory import create_app
from consts.exceptions import (
    DistributedStateUnavailable,
    LimitExceededError,
    UnauthorizedError,
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


def _build_request(auth="Bearer test-access-key", request_id="req-123"):
    """Build a minimal Starlette request for context-resolution tests."""
    headers = [(b"authorization", auth.encode())]
    if request_id is not None:
        headers.append((b"x-request-id", request_id.encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.mark.asyncio
async def test_get_northbound_context_resolves_identity_and_request_id():
    """A valid access key resolves the shared northbound request context."""
    with patch("apps.northbound_app.validate_bearer_token", return_value=(True, {"sub": "user-1"})), \
            patch("apps.northbound_app.get_user_and_tenant_by_access_key", return_value={
                "user_id": "user-1", "tenant_id": "tenant-1", "token_id": 7,
            }):
        context = await _get_northbound_context(_build_request())

    assert context.user_id == "user-1"
    assert context.tenant_id == "tenant-1"
    assert context.token_id == 7
    assert context.request_id == "req-123"
    assert context.authorization == "Bearer test-access-key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("validation_error", "expected_status", "expected_detail"),
    [
        (LimitExceededError("limited"), 429, "Too Many Requests"),
        (UnauthorizedError("revoked"), 401, "revoked"),
        (RuntimeError("database unavailable"), 401, "Unauthorized: invalid API key"),
    ],
)
async def test_get_northbound_context_maps_validation_errors(
    validation_error, expected_status, expected_detail
):
    """Authentication failures preserve their public HTTP contract."""
    with patch("apps.northbound_app.validate_bearer_token", side_effect=validation_error):
        with pytest.raises(HTTPException) as exc_info:
            await _get_northbound_context(_build_request())

    assert exc_info.value.status_code == expected_status
    assert expected_detail in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_northbound_context_rejects_invalid_token():
    """An absent or invalid bearer token is rejected before identity lookup."""
    with patch("apps.northbound_app.validate_bearer_token", return_value=(False, None)), \
            patch("apps.northbound_app.get_user_and_tenant_by_access_key") as identity_lookup:
        with pytest.raises(HTTPException) as exc_info:
            await _get_northbound_context(_build_request())

    assert exc_info.value.status_code == 401
    identity_lookup.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity", "expected_detail"),
    [
        ({"user_id": None, "tenant_id": "tenant-1", "token_id": 7}, "Missing user information"),
        ({"user_id": "user-1", "tenant_id": None, "token_id": 7}, "Missing tenant information"),
    ],
)
async def test_get_northbound_context_requires_user_and_tenant(identity, expected_detail):
    """A valid token must map to both a user and a tenant."""
    with patch("apps.northbound_app.validate_bearer_token", return_value=(True, {"sub": "user-1"})), \
            patch("apps.northbound_app.get_user_and_tenant_by_access_key", return_value=identity):
        with pytest.raises(HTTPException) as exc_info:
            await _get_northbound_context(_build_request())

    assert exc_info.value.status_code == 400
    assert expected_detail in str(exc_info.value.detail)


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


def test_run_chat_distributed_state_failure_returns_503():
    """Northbound must not rewrite required Redis failures as 500 or 429."""
    handled_app = create_app(enable_monitoring=False)
    handled_app.include_router(router)
    handled_client = TestClient(handled_app, raise_server_exceptions=False)

    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.start_streaming_chat', new_callable=AsyncMock) as mock_run:
        mock_ctx.return_value = MagicMock()
        mock_run.side_effect = DistributedStateUnavailable("redis down")

        response = handled_client.post(
            "/nb/v1/chat/run",
            json={"agent_name": "general-assistant", "query": "Hello"},
            headers=_build_headers(),
        )

    assert response.status_code == 503
    assert response.json()["code"] == "distributed_state_unavailable"


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


def test_update_conversation_title_distributed_state_failure_returns_503():
    """Title idempotency must preserve required Redis failures as HTTP 503."""
    handled_app = create_app(enable_monitoring=False)
    handled_app.include_router(router)
    handled_client = TestClient(handled_app, raise_server_exceptions=False)

    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.update_conversation_title', new_callable=AsyncMock) as mock_update:
        mock_ctx.return_value = MagicMock(request_id="req-123")
        mock_update.side_effect = DistributedStateUnavailable("redis down")

        response = handled_client.put(
            "/nb/v1/conversations/123/title?title=New%20Title",
            headers=_build_headers(),
        )

    assert response.status_code == 503
    assert response.json()["code"] == "distributed_state_unavailable"


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


def test_file_fetch_proxies_content_and_filename():
    """The proxy streams upstream bytes with a stable download filename."""
    response = MagicMock(status_code=200)
    response.headers = {
        "Content-Type": "text/plain",
        "Content-Disposition": "attachment; filename*=UTF-8''report%20final.txt",
    }

    async def stream_bytes():
        yield b"report contents"

    response.aiter_bytes = stream_bytes
    upstream_client = AsyncMock()
    upstream_client.get.return_value = response
    client_context = AsyncMock()
    client_context.__aenter__.return_value = upstream_client

    with patch("apps.northbound_app.httpx.AsyncClient", return_value=client_context):
        result = client.get(
            "/nb/v1/file/fetch",
            params={"presigned_url": "https://storage.example/reports/original.txt"},
        )

    assert result.status_code == 200
    assert result.content == b"report contents"
    assert result.headers["content-type"].startswith("text/plain")
    assert 'filename="report final.txt"' in result.headers["content-disposition"]


@pytest.mark.parametrize(
    ("side_effect", "expected_status"),
    [
        (httpx.TimeoutException("timeout"), 504),
        (httpx.RequestError("connection failed"), 502),
        (RuntimeError("unexpected"), 500),
    ],
)
def test_file_fetch_maps_upstream_failures(side_effect, expected_status):
    """The proxy distinguishes timeout, transport, and unexpected failures."""
    upstream_client = AsyncMock()
    upstream_client.get.side_effect = side_effect
    client_context = AsyncMock()
    client_context.__aenter__.return_value = upstream_client

    with patch("apps.northbound_app.httpx.AsyncClient", return_value=client_context):
        result = client.get(
            "/nb/v1/file/fetch",
            params={"presigned_url": "https://storage.example/reports/report.txt"},
        )

    assert result.status_code == expected_status


def test_file_fetch_rejects_invalid_scheme_and_upstream_status():
    """The proxy rejects unsafe schemes and non-success storage responses."""
    invalid_scheme = client.get(
        "/nb/v1/file/fetch",
        params={"presigned_url": "file:///etc/passwd"},
    )
    assert invalid_scheme.status_code == 400

    response = MagicMock(status_code=404, headers={})
    upstream_client = AsyncMock()
    upstream_client.get.return_value = response
    client_context = AsyncMock()
    client_context.__aenter__.return_value = upstream_client
    with patch("apps.northbound_app.httpx.AsyncClient", return_value=client_context):
        upstream_failure = client.get(
            "/nb/v1/file/fetch",
            params={"presigned_url": "https://storage.example/missing.txt"},
        )

    assert upstream_failure.status_code == 502


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


def test_stop_chat_distributed_state_failure_returns_503():
    """Cross-Pod stop must preserve required Redis failures as HTTP 503."""
    handled_app = create_app(enable_monitoring=False)
    handled_app.include_router(router)
    handled_client = TestClient(handled_app, raise_server_exceptions=False)

    with patch('apps.northbound_app._get_northbound_context', new_callable=AsyncMock) as mock_ctx, \
            patch('apps.northbound_app.stop_chat', new_callable=AsyncMock) as mock_stop:
        mock_ctx.return_value = MagicMock()
        mock_stop.side_effect = DistributedStateUnavailable("redis down")

        response = handled_client.get(
            "/nb/v1/chat/stop/123",
            headers=_build_headers(),
        )

    assert response.status_code == 503
    assert response.json()["code"] == "distributed_state_unavailable"


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
