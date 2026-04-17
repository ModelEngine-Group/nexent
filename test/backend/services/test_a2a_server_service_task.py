"""
Unit tests for A2A Server Service - Task Management.

This module contains tests for:
- _validate_endpoint, _resolve_task_id methods
- get_task, list_tasks, list_tasks_paginated, cancel_task methods
"""
import pytest
from unittest.mock import MagicMock, patch


class TestValidateEndpoint:
    """Test class for _validate_endpoint method."""

    def test_validate_endpoint_success(self):
        """Test successful endpoint validation."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_server_agent = {
            "endpoint_id": "test-endpoint",
            "agent_id": 1,
            "is_enabled": True
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_server_agent

            result = service._validate_endpoint("test-endpoint")

            assert result == mock_server_agent
            mock_db.get_server_agent_by_endpoint.assert_called_once_with("test-endpoint")

    def test_validate_endpoint_not_found(self):
        """Test endpoint validation when endpoint not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            EndpointNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = None

            with pytest.raises(EndpointNotFoundError) as exc_info:
                service._validate_endpoint("nonexistent")

            assert "not found" in str(exc_info.value)

    def test_validate_endpoint_disabled(self):
        """Test endpoint validation when endpoint is disabled."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            AgentNotEnabledError
        )

        service = A2AServerService()

        mock_server_agent = {
            "endpoint_id": "test-endpoint",
            "is_enabled": False
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_server_agent

            with pytest.raises(AgentNotEnabledError) as exc_info:
                service._validate_endpoint("test-endpoint")

            assert "not enabled" in str(exc_info.value)


class TestResolveTaskId:
    """Test class for _resolve_task_id method."""

    def test_resolve_task_id_with_existing_client_task_id(self):
        """Test resolving task ID when client provides existing taskId."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        parsed_message = {
            "message": {"taskId": "task_123"},
            "history": []
        }
        server_agent = {"endpoint_id": "test-endpoint"}

        mock_existing_task = {
            "id": "task_123",
            "task_state": "TASK_STATE_WORKING"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_existing_task

            task_id, context_id, is_complex = service._resolve_task_id(
                parsed_message, "test-endpoint", "user-1", "tenant-1", server_agent
            )

            assert task_id == "task_123"
            assert is_complex is True

    def test_resolve_task_id_with_terminal_task(self):
        """Test resolving task ID when task is already terminal."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            UnsupportedOperationError
        )

        service = A2AServerService()

        parsed_message = {
            "message": {"taskId": "task_completed"},
            "history": []
        }
        server_agent = {"endpoint_id": "test-endpoint"}

        mock_task = {
            "id": "task_completed",
            "task_state": "TASK_STATE_COMPLETED"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task

            with pytest.raises(UnsupportedOperationError) as exc_info:
                service._resolve_task_id(
                    parsed_message, "test-endpoint", "user-1", "tenant-1", server_agent
                )

            assert "already terminated" in str(exc_info.value)

    def test_resolve_task_id_with_context_id_creates_new_task(self):
        """Test creating new task when contextId is present."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        parsed_message = {
            "message": {"contextId": "ctx_456"},
            "history": []
        }
        server_agent = {"endpoint_id": "test-endpoint"}

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = None
            mock_db.create_task.return_value = MagicMock()

            task_id, context_id, is_complex = service._resolve_task_id(
                parsed_message, "test-endpoint", "user-1", "tenant-1", server_agent
            )

            assert task_id is not None
            assert task_id.startswith("task_")
            assert context_id == "ctx_456"
            assert is_complex is True
            mock_db.create_task.assert_called_once()

    def test_resolve_task_id_with_history_creates_new_task(self):
        """Test creating new task when history is present."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        parsed_message = {
            "message": {},
            "history": [{"role": "user", "content": "Hello"}]
        }
        server_agent = {"endpoint_id": "test-endpoint"}

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = None
            mock_db.create_task.return_value = MagicMock()

            task_id, context_id, is_complex = service._resolve_task_id(
                parsed_message, "test-endpoint", "user-1", "tenant-1", server_agent
            )

            assert task_id is not None
            assert is_complex is True
            mock_db.create_task.assert_called_once()

    def test_resolve_task_id_simple_request(self):
        """Test simple request without complex flags."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        parsed_message = {
            "message": {"parts": [{"type": "text", "text": "Hello"}]},
            "history": []
        }
        server_agent = {"endpoint_id": "test-endpoint"}

        task_id, context_id, is_complex = service._resolve_task_id(
            parsed_message, "test-endpoint", "user-1", "tenant-1", server_agent
        )

        assert task_id is None
        assert context_id is None
        assert is_complex is False


class TestGetTask:
    """Test class for get_task method."""

    def test_get_task_success(self):
        """Test successful get_task."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_task = {
            "id": "task_123",
            "task_state": "TASK_STATE_COMPLETED",
            "caller_user_id": "user-1",
            "context_id": "ctx_456",
            "result": {"message": "Hello, how can I help?"},
            "update_time": "2024-01-01T00:00:00Z"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task

            result = service.get_task("task_123", user_id="user-1")

            assert result["id"] == "task_123"
            assert result["status"]["state"] == "TASK_STATE_COMPLETED"
            assert result["contextId"] == "ctx_456"
            assert "artifacts" in result

    def test_get_task_not_found(self):
        """Test get_task when task not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            TaskNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = None

            with pytest.raises(TaskNotFoundError) as exc_info:
                service.get_task("nonexistent")

            assert "not found" in str(exc_info.value)

    def test_get_task_unauthorized(self):
        """Test get_task with wrong user_id."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            A2AServerServiceError
        )

        service = A2AServerService()

        mock_task = {
            "id": "task_123",
            "caller_user_id": "user-1",
            "task_state": "TASK_STATE_WORKING"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task

            with pytest.raises(A2AServerServiceError) as exc_info:
                service.get_task("task_123", user_id="wrong-user")

            assert "Unauthorized" in str(exc_info.value)

    def test_get_task_without_authorization(self):
        """Test get_task without user_id (no authorization check)."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_task = {
            "id": "task_123",
            "task_state": "TASK_STATE_WORKING",
            "caller_user_id": "user-1"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task

            result = service.get_task("task_123")

            assert result["id"] == "task_123"

    def test_get_task_state_mapping(self):
        """Test task state mapping to A2A format."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_task = {
            "id": "task_123",
            "task_state": "TASK_STATE_FAILED",
            "caller_user_id": "user-1",
            "result": {"error": "Something went wrong"}
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task

            result = service.get_task("task_123", user_id="user-1")

            assert result["status"]["state"] == "TASK_STATE_FAILED"


class TestListTasks:
    """Test class for list_tasks method."""

    def test_list_tasks_basic(self):
        """Test basic list_tasks."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_tasks = [
            {"id": "task_1", "task_state": "TASK_STATE_WORKING"},
            {"id": "task_2", "task_state": "TASK_STATE_COMPLETED"}
        ]

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.list_tasks.return_value = mock_tasks

            result = service.list_tasks(tenant_id="tenant-1")

            assert len(result) == 2
            mock_db.list_tasks.assert_called_once()

    def test_list_tasks_with_filters(self):
        """Test list_tasks with various filters."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_tasks = [
            {"id": "task_1", "endpoint_id": "ep_1", "task_state": "TASK_STATE_WORKING"}
        ]

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.list_tasks.return_value = mock_tasks

            result = service.list_tasks(
                endpoint_id="ep_1",
                user_id="user-1",
                tenant_id="tenant-1",
                status="TASK_STATE_WORKING",
                limit=10,
                offset=0
            )

            assert len(result) == 1
            call_kwargs = mock_db.list_tasks.call_args.kwargs
            assert call_kwargs["endpoint_id"] == "ep_1"
            assert call_kwargs["limit"] == 10


class TestListTasksPaginated:
    """Test class for list_tasks_paginated method."""

    def test_list_tasks_paginated_success(self):
        """Test list_tasks_paginated with results."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_tasks = [
            {"id": "task_1", "task_state": "TASK_STATE_WORKING"}
        ]

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.list_tasks_paginated.return_value = (mock_tasks, "next_cursor_token")

            tasks, next_token = service.list_tasks_paginated(
                tenant_id="tenant-1",
                limit=10
            )

            assert len(tasks) == 1
            assert next_token == "next_cursor_token"

    def test_list_tasks_paginated_no_next_page(self):
        """Test list_tasks_paginated when no more pages."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_tasks = [
            {"id": "task_1"}
        ]

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.list_tasks_paginated.return_value = (mock_tasks, None)

            tasks, next_token = service.list_tasks_paginated(
                tenant_id="tenant-1",
                limit=10
            )

            assert len(tasks) == 1
            assert next_token is None

    def test_list_tasks_paginated_with_cursor(self):
        """Test list_tasks_paginated with cursor."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_cursor = {"update_time": "2024-01-01T00:00:00Z"}
        mock_tasks = [{"id": "task_1"}]

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.list_tasks_paginated.return_value = (mock_tasks, None)

            tasks, next_token = service.list_tasks_paginated(
                tenant_id="tenant-1",
                cursor=mock_cursor
            )

            call_kwargs = mock_db.list_tasks_paginated.call_args.kwargs
            assert call_kwargs["cursor"] == mock_cursor


class TestCancelTask:
    """Test class for cancel_task method."""

    def test_cancel_task_success(self):
        """Test successful task cancellation."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        mock_task = {
            "id": "task_123",
            "caller_user_id": "user-1",
            "task_state": "TASK_STATE_CANCELED"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task
            mock_db.cancel_task.return_value = True

            result = service.cancel_task("task_123", user_id="user-1")

            assert result["task_state"] == "TASK_STATE_CANCELED"

    def test_cancel_task_not_found(self):
        """Test cancel_task when task not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            TaskNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = None

            with pytest.raises(TaskNotFoundError) as exc_info:
                service.cancel_task("nonexistent")

            assert "not found" in str(exc_info.value)

    def test_cancel_task_unauthorized(self):
        """Test cancel_task with wrong user_id."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            A2AServerServiceError
        )

        service = A2AServerService()

        mock_task = {
            "id": "task_123",
            "caller_user_id": "user-1"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task

            with pytest.raises(A2AServerServiceError) as exc_info:
                service.cancel_task("task_123", user_id="wrong-user")

            assert "Unauthorized" in str(exc_info.value)

    def test_cancel_task_cannot_cancel(self):
        """Test cancel_task when task cannot be canceled (already completed)."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            A2AServerServiceError
        )

        service = A2AServerService()

        mock_task = {
            "id": "task_123",
            "caller_user_id": "user-1",
            "task_state": "TASK_STATE_COMPLETED"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_task.return_value = mock_task
            mock_db.cancel_task.return_value = False

            with pytest.raises(A2AServerServiceError) as exc_info:
                service.cancel_task("task_123", user_id="user-1")

            assert "cannot be canceled" in str(exc_info.value)
