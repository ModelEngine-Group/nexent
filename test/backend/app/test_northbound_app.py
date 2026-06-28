"""Unit tests for backend.apps.northbound_app module."""
import sys
import os

# The conftest.py sets up all mocks

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from io import BytesIO

# Import from conftest (which sets up mocks automatically)
from apps.northbound_app import router
from consts.exceptions import (
    LimitExceededError,
    UnauthorizedError,
    SignatureValidationError,
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
