"""
Unit tests for A2A Server Service.

Tests the A2AServerService class in backend/services/a2a_server_service.py.
"""
import sys
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

# Mock database modules before importing the service
_agent_db_mock = MagicMock()
sys.modules['database.agent_db'] = _agent_db_mock
sys.modules['backend.database.agent_db'] = _agent_db_mock


class TestA2AServerServiceExceptions:
    """Test class for A2A Server Service exceptions."""

    def test_base_exception_exists(self):
        """Test A2AServerServiceError exception exists."""
        from backend.services.a2a_server_service import A2AServerServiceError

        exc = A2AServerServiceError("Test error")
        assert str(exc) == "Test error"

    def test_endpoint_not_found_error_exists(self):
        """Test EndpointNotFoundError exception exists."""
        from backend.services.a2a_server_service import EndpointNotFoundError

        exc = EndpointNotFoundError("Endpoint not found")
        assert str(exc) == "Endpoint not found"

    def test_agent_not_enabled_error_exists(self):
        """Test AgentNotEnabledError exception exists."""
        from backend.services.a2a_server_service import AgentNotEnabledError

        exc = AgentNotEnabledError("Agent not enabled")
        assert str(exc) == "Agent not enabled"

    def test_task_not_found_error_exists(self):
        """Test TaskNotFoundError exception exists."""
        from backend.services.a2a_server_service import TaskNotFoundError

        exc = TaskNotFoundError("Task not found")
        assert str(exc) == "Task not found"

    def test_unsupported_operation_error_exists(self):
        """Test UnsupportedOperationError exception exists."""
        from backend.services.a2a_server_service import UnsupportedOperationError

        exc = UnsupportedOperationError("Unsupported operation")
        assert str(exc) == "Unsupported operation"


class TestA2AServerServiceInit:
    """Test class for A2AServerService initialization."""

    def test_initialization(self):
        """Test service can be instantiated."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()
        assert service is not None
        assert service.adapter is not None


class TestHelperFunctions:
    """Test class for module helper functions."""

    def test_generate_task_id(self):
        """Test task ID generation."""
        from backend.services.a2a_server_service import _generate_task_id

        task_id = _generate_task_id()
        assert task_id.startswith("task_")
        assert len(task_id) > 5

    def test_generate_task_id_unique(self):
        """Test task ID generation is unique."""
        from backend.services.a2a_server_service import _generate_task_id

        ids = [_generate_task_id() for _ in range(10)]
        assert len(set(ids)) == 10

    def test_generate_endpoint_id(self):
        """Test endpoint ID generation."""
        from backend.services.a2a_server_service import _generate_endpoint_id

        endpoint_id = _generate_endpoint_id(agent_id=123)
        assert endpoint_id.startswith("a2a_123_")
        assert len(endpoint_id) > 10

    def test_generate_endpoint_id_unique(self):
        """Test endpoint ID generation is unique."""
        from backend.services.a2a_server_service import _generate_endpoint_id

        ids = [_generate_endpoint_id(123) for _ in range(10)]
        assert len(set(ids)) == 10


class TestResolveBaseUrl:
    """Test class for _resolve_base_url method."""

    def test_uses_northbound_url(self):
        """Test uses NORTHBOUND_EXTERNAL_URL when use_northbound=True."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.NORTHBOUND_EXTERNAL_URL", "https://api.example.com"):
            result = service._resolve_base_url(use_northbound=True, base_url="https://other.com")
            assert result == "https://api.example.com"

    def test_uses_base_url_when_no_northbound(self):
        """Test uses base_url when use_northbound=False."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._resolve_base_url(use_northbound=False, base_url="https://other.com")
        assert result == "https://other.com"

    def test_returns_empty_when_no_url(self):
        """Test returns empty string when no URL available."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.NORTHBOUND_EXTERNAL_URL", ""):
            result = service._resolve_base_url(use_northbound=True, base_url=None)
            assert result == ""


class TestResolveAgentUrl:
    """Test class for _resolve_agent_url method."""

    def test_prefers_stored_url(self):
        """Test prefers stored URL over base."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._resolve_agent_url(
            stored_url="https://stored.com",
            effective_base="https://base.com"
        )
        assert result == "https://stored.com"

    def test_uses_base_when_no_stored(self):
        """Test uses base URL when no stored URL."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._resolve_agent_url(
            stored_url=None,
            effective_base="https://base.com/"
        )
        assert result == "https://base.com"

    def test_handles_empty_base(self):
        """Test handles empty base URL."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._resolve_agent_url(
            stored_url=None,
            effective_base=""
        )
        assert result == ""


class TestBuildAgentCardBase:
    """Test class for _build_agent_card_base method."""

    def test_builds_complete_card(self):
        """Test building complete agent card."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_agent_card_base(
            name="Test Agent",
            description="A test agent",
            version="1.0.0",
            streaming=True,
            effective_base_url="https://api.example.com",
            supported_interfaces=[{"protocolBinding": "http-json-rpc", "url": "https://api.example.com/v1"}],
            agent_url="https://api.example.com",
            agent_info={"name": "Test Agent", "description": "Test"}
        )

        assert result["name"] == "Test Agent"
        assert result["description"] == "A test agent"
        assert result["version"] == "1.0.0"
        assert result["capabilities"]["streaming"] is True
        assert result["capabilities"]["pushNotifications"] is False
        assert "provider" in result
        assert result["provider"]["organization"] == "Nexent"

    def test_includes_default_modes(self):
        """Test includes default input/output modes."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_agent_card_base(
            name="Test",
            description="Test",
            version="1.0",
            streaming=False,
            effective_base_url="https://api.example.com",
            supported_interfaces=[],
            agent_url="https://api.example.com",
            agent_info={}
        )

        assert "text/plain" in result["defaultInputModes"]
        assert "text/plain" in result["defaultOutputModes"]

    def test_includes_skills(self):
        """Test includes skills from agent info."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_agent_card_base(
            name="Test Agent",
            description="Test agent",
            version="1.0",
            streaming=False,
            effective_base_url="https://api.example.com",
            supported_interfaces=[],
            agent_url="https://api.example.com",
            agent_info={"name": "Test Agent", "description": "A helpful agent"}
        )

        assert len(result["skills"]) > 0
        assert result["skills"][0]["id"] == "chat"


class TestBuildSupportedInterfaces:
    """Test class for _build_supported_interfaces method."""

    def test_builds_interfaces_with_prefix(self):
        """Test building supported interfaces with prefix."""
        from backend.services.a2a_server_service import A2AServerService
        from database.a2a_agent_db import PROTOCOL_HTTP_JSON, PROTOCOL_JSONRPC

        service = A2AServerService()

        result = service._build_supported_interfaces(
            base_url="https://api.example.com",
            endpoint_id="test-endpoint",
            prefix="/nb/a2a"
        )

        assert len(result) == 2
        assert result[0]["protocolBinding"] == PROTOCOL_JSONRPC
        assert "/nb/a2a/test-endpoint/v1" in result[0]["url"]
        assert result[1]["protocolBinding"] == PROTOCOL_HTTP_JSON
        assert "/nb/a2a/test-endpoint" in result[1]["url"]

    def test_handles_base_url_without_trailing_slash(self):
        """Test handles base URL without trailing slash."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_supported_interfaces(
            base_url="https://api.example.com",
            endpoint_id="test",
            prefix="/a2a"
        )

        assert result[0]["url"].startswith("https://api.example.com/a2a/")

    def test_handles_empty_base_url(self):
        """Test handles empty base URL."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_supported_interfaces(
            base_url="",
            endpoint_id="test",
            prefix="/a2a"
        )

        assert result[0]["url"] == "/a2a/test/v1"


class TestBuildSkillsFromAgent:
    """Test class for _build_skills_from_agent method."""

    def test_builds_default_skill(self):
        """Test building default chat skill."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_skills_from_agent({
            "name": "Test Agent",
            "description": "A test agent"
        })

        assert len(result) == 1
        assert result[0]["id"] == "chat"
        assert result[0]["name"] == "Test Agent"
        assert "chat" in result[0]["tags"]
        assert "conversation" in result[0]["tags"]

    def test_handles_missing_fields(self):
        """Test handles missing agent info fields."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        result = service._build_skills_from_agent({})

        assert result[0]["name"] == "Nexent Agent"


class TestValidateEndpoint:
    """Test class for _validate_endpoint method."""

    def test_returns_server_agent_when_valid(self):
        """Test returns server agent when valid."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_agent = {
            "endpoint_id": "test-123",
            "is_enabled": True
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_agent

            result = service._validate_endpoint("test-123")
            assert result == mock_agent

    def test_raises_error_when_not_found(self):
        """Test raises error when endpoint not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            EndpointNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = None

            with pytest.raises(EndpointNotFoundError):
                service._validate_endpoint("nonexistent")

    def test_raises_error_when_disabled(self):
        """Test raises error when agent not enabled."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            AgentNotEnabledError
        )

        service = A2AServerService()

        mock_agent = {
            "endpoint_id": "test-123",
            "is_enabled": False
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_agent

            with pytest.raises(AgentNotEnabledError):
                service._validate_endpoint("test-123")


class TestResolveTaskId:
    """Test class for _resolve_task_id method."""

    def test_returns_existing_task_id(self):
        """Test returns existing task ID when provided."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        parsed_message = {
            "message": {
                "taskId": "existing-task-123"
            }
        }

        mock_existing_task = {
            "id": "existing-task-123",
            "task_state": "TASK_STATE_WORKING"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_existing_task

            task_id, context_id, is_complex = service._resolve_task_id(
                parsed_message,
                endpoint_id="test-endpoint",
                user_id="user-1",
                tenant_id="tenant-1",
                server_agent={"agent_id": 1}
            )

            assert task_id == "existing-task-123"
            assert context_id is None
            assert is_complex is True

    def test_generates_new_task_id_for_complex_request(self):
        """Test generates new task ID for complex request without taskId."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        parsed_message = {
            "message": {
                "contextId": "ctx-123"
            }
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = None  # No existing task
            mock_db.create_task.return_value = {}

            task_id, context_id, is_complex = service._resolve_task_id(
                parsed_message,
                endpoint_id="test-endpoint",
                user_id="user-1",
                tenant_id="tenant-1",
                server_agent={"agent_id": 1}
            )

            assert task_id.startswith("task_")
            assert context_id == "ctx-123"
            assert is_complex is True

    def test_returns_none_task_id_for_simple_request(self):
        """Test returns None task ID for simple request."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        parsed_message = {
            "message": {
                "parts": [{"type": "text", "text": "Hello"}]
            }
        }

        task_id, context_id, is_complex = service._resolve_task_id(
            parsed_message,
            endpoint_id="test-endpoint",
            user_id="user-1",
            tenant_id="tenant-1",
            server_agent={"agent_id": 1}
        )

        assert task_id is None
        assert context_id is None
        assert is_complex is False

    def test_raises_error_for_nonexistent_task(self):
        """Test raises error when task ID references nonexistent task."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            TaskNotFoundError
        )

        service = A2AServerService()

        parsed_message = {
            "message": {
                "taskId": "nonexistent-task"
            }
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = None

            with pytest.raises(TaskNotFoundError):
                service._resolve_task_id(
                    parsed_message,
                    endpoint_id="test-endpoint",
                    user_id="user-1",
                    tenant_id="tenant-1",
                    server_agent={"agent_id": 1}
                )

    def test_raises_error_for_terminal_task(self):
        """Test raises error when task is already terminated."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            UnsupportedOperationError
        )

        service = A2AServerService()

        parsed_message = {
            "message": {
                "taskId": "completed-task"
            }
        }

        mock_task = {
            "id": "completed-task",
            "task_state": "TASK_STATE_COMPLETED"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task

            with pytest.raises(UnsupportedOperationError):
                service._resolve_task_id(
                    parsed_message,
                    endpoint_id="test-endpoint",
                    user_id="user-1",
                    tenant_id="tenant-1",
                    server_agent={"agent_id": 1}
                )


class TestGetAgentCard:
    """Test class for get_agent_card method."""

    def test_raises_error_when_not_found(self):
        """Test raises error when endpoint not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            EndpointNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = None

            with pytest.raises(EndpointNotFoundError):
                service.get_agent_card("nonexistent-endpoint")

    def test_raises_error_when_disabled(self):
        """Test raises error when endpoint is disabled."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            EndpointNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = {
                "endpoint_id": "test",
                "is_enabled": False
            }

            with pytest.raises(EndpointNotFoundError):
                service.get_agent_card("test")

    def test_returns_agent_card(self):
        """Test returns agent card."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_server_agent = {
            "endpoint_id": "test-endpoint",
            "agent_id": 1,
            "tenant_id": "tenant-1",
            "is_enabled": True,
            "name": "Test Agent",
            "description": "A test agent",
            "version": "1.0.0",
            "streaming": True,
            "card_overrides": {"tags": ["test"]}
        }

        mock_agent_info = {
            "name": "Local Agent",
            "description": "Local description"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_server_agent

            with patch.object(_agent_db_mock, 'search_agent_info_by_agent_id', return_value=mock_agent_info):

                with patch("backend.services.a2a_server_service.NORTHBOUND_EXTERNAL_URL", "https://api.example.com"):
                    result = service.get_agent_card(
                        "test-endpoint",
                        use_northbound=True
                    )

                    assert result["name"] == "Test Agent"
                    assert result["tags"] == ["test"]


class TestGetTask:
    """Test class for get_task method."""

    def test_returns_task(self):
        """Test returns task."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_task = {
            "id": "task-123",
            "task_state": "TASK_STATE_COMPLETED",
            "context_id": "ctx-456",
            "result": {"message": "Hello"}
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task

            result = service.get_task("task-123")

            assert result["id"] == "task-123"
            assert result["status"]["state"] == "TASK_STATE_COMPLETED"
            assert "artifacts" in result

    def test_raises_error_when_not_found(self):
        """Test raises error when task not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            TaskNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = None

            with pytest.raises(TaskNotFoundError):
                service.get_task("nonexistent-task")

    def test_raises_error_for_unauthorized_user(self):
        """Test raises error for unauthorized user."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            A2AServerServiceError
        )

        service = A2AServerService()

        mock_task = {
            "id": "task-123",
            "task_state": "TASK_STATE_WORKING",
            "caller_user_id": "owner-user"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task

            with pytest.raises(A2AServerServiceError, match="Unauthorized"):
                service.get_task("task-123", user_id="other-user")


class TestListTasks:
    """Test class for list_tasks method."""

    def test_calls_db_with_filters(self):
        """Test calls database with filters."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_tasks = [
            {"id": "task-1"},
            {"id": "task-2"}
        ]

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.list_tasks.return_value = mock_tasks

            result = service.list_tasks(
                endpoint_id="test-endpoint",
                user_id="user-1",
                tenant_id="tenant-1",
                status="TASK_STATE_COMPLETED",
                limit=10
            )

            assert len(result) == 2
            mock_db.list_tasks.assert_called_once()


class TestCancelTask:
    """Test class for cancel_task method."""

    def test_cancels_task(self):
        """Test canceling task."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_task = {
            "id": "task-123",
            "task_state": "TASK_STATE_WORKING",
            "caller_user_id": "user-1"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task
            mock_db.cancel_task.return_value = True
            mock_db.get_task.return_value = {**mock_task, "task_state": "TASK_STATE_CANCELED"}

            result = service.cancel_task("task-123", user_id="user-1")

            mock_db.cancel_task.assert_called_once_with("task-123")

    def test_raises_error_when_not_found(self):
        """Test raises error when task not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            TaskNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = None

            with pytest.raises(TaskNotFoundError):
                service.cancel_task("nonexistent-task")

    def test_raises_error_for_unauthorized_user(self):
        """Test raises error for unauthorized user."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            A2AServerServiceError
        )

        service = A2AServerService()

        mock_task = {
            "id": "task-123",
            "caller_user_id": "owner"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task

            with pytest.raises(A2AServerServiceError):
                service.cancel_task("task-123", user_id="other-user")


class TestTerminalStates:
    """Test class for terminal states constant."""

    def test_terminal_states_defined(self):
        """Test terminal states are defined."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        assert "TASK_STATE_COMPLETED" in service.TERMINAL_STATES
        assert "TASK_STATE_FAILED" in service.TERMINAL_STATES
        assert "TASK_STATE_CANCELED" in service.TERMINAL_STATES


class TestSingletonInstance:
    """Test class for singleton instance."""

    def test_singleton_exists(self):
        """Test that singleton instance exists."""
        from backend.services.a2a_server_service import a2a_server_service

        assert a2a_server_service is not None


class TestStoreMethods:
    """Test class for storage helper methods."""

    def test_store_user_message(self):
        """Test storing user message."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        message_obj = {
            "role": "ROLE_USER",
            "parts": [{"type": "text", "text": "Hello"}]
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            service._store_user_message("task-123", message_obj, "endpoint-456")

            mock_db.create_message.assert_called_once()
            call_kwargs = mock_db.create_message.call_args[1]
            assert call_kwargs["task_id"] == "task-123"
            assert call_kwargs["role"] == "ROLE_USER"

    def test_store_user_message_with_text_fallback(self):
        """Test storing user message with text fallback."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        message_obj = {
            "role": "ROLE_USER",
            "text": "Hello from text field"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            service._store_user_message("task-123", message_obj, "endpoint-456")

            mock_db.create_message.assert_called_once()

    def test_store_agent_response(self):
        """Test storing agent response."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            service._store_agent_response("task-123", "Agent response text", "endpoint-456")

            mock_db.create_message.assert_called_once()
            mock_db.update_task_state.assert_called_once()

            call_kwargs = mock_db.update_task_state.call_args[1]
            assert call_kwargs["task_id"] == "task-123"
            assert call_kwargs["task_state"] == "TASK_STATE_COMPLETED"

    def test_store_agent_response_empty_text(self):
        """Test storing agent response with empty text."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            service._store_agent_response("task-123", "", "endpoint-456")

            mock_db.create_message.assert_called_once()

    def test_store_error_response(self):
        """Test storing error response."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            service._store_error_response("task-123", "Something went wrong", "endpoint-456")

            mock_db.create_message.assert_called_once()
            mock_db.update_task_state.assert_called_once()

            call_kwargs = mock_db.update_task_state.call_args[1]
            assert call_kwargs["task_state"] == "TASK_STATE_FAILED"
