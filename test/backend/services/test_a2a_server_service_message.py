"""
Unit tests for A2A Server Service - Message Handling.

This module contains tests for:
- _store_user_message, _store_agent_response, _store_error_response methods
- _collect_stream_text method
- handle_message_send, handle_message_stream error cases
- helper functions
"""
import pytest
pytest_plugins = ['pytest_asyncio']
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import json


class TestStoreUserMessage:
    """Test class for _store_user_message method."""

    def test_store_user_message_with_parts(self):
        """Test storing user message with parts."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        message_obj = {
            "parts": [
                {"type": "text", "text": "Hello, how are you?"}
            ]
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.create_message.return_value = MagicMock()

            service._store_user_message("task_123", message_obj, "test-endpoint")

            mock_db.create_message.assert_called_once()
            call_kwargs = mock_db.create_message.call_args.kwargs
            assert call_kwargs["task_id"] == "task_123"
            assert call_kwargs["role"] == "ROLE_USER"
            assert call_kwargs["parts"] == message_obj["parts"]

    def test_store_user_message_with_text_field(self):
        """Test storing user message using text field when no parts."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        message_obj = {
            "text": "Just a text message"
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.create_message.return_value = MagicMock()

            service._store_user_message("task_123", message_obj, "test-endpoint")

            mock_db.create_message.assert_called_once()
            call_kwargs = mock_db.create_message.call_args.kwargs
            expected_parts = [{"text": "Just a text message"}]
            assert call_kwargs["parts"] == expected_parts

    def test_store_user_message_empty(self):
        """Test storing empty user message."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        message_obj = {}

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.create_message.return_value = MagicMock()

            service._store_user_message("task_123", message_obj, "test-endpoint")

            mock_db.create_message.assert_called_once()
            call_kwargs = mock_db.create_message.call_args.kwargs
            assert call_kwargs["parts"] == []


class TestStoreAgentResponse:
    """Test class for _store_agent_response method."""

    def test_store_agent_response_success(self):
        """Test storing successful agent response."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.create_message.return_value = MagicMock()
            mock_db.update_task_state.return_value = MagicMock()

            service._store_agent_response("task_123", "Hello, I am fine!", "test-endpoint")

            mock_db.create_message.assert_called_once()
            call_kwargs = mock_db.create_message.call_args.kwargs
            assert call_kwargs["role"] == "ROLE_AGENT"
            assert call_kwargs["parts"][0]["text"] == "Hello, I am fine!"

            mock_db.update_task_state.assert_called_once()
            call_kwargs = mock_db.update_task_state.call_args.kwargs
            assert call_kwargs["task_id"] == "task_123"
            assert call_kwargs["task_state"] == "TASK_STATE_COMPLETED"

    def test_store_agent_response_empty_text(self):
        """Test storing empty agent response."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.create_message.return_value = MagicMock()
            mock_db.update_task_state.return_value = MagicMock()

            service._store_agent_response("task_123", "", "test-endpoint")

            mock_db.create_message.assert_called_once()
            call_kwargs = mock_db.create_message.call_args.kwargs
            assert call_kwargs["parts"] == []

    def test_store_agent_response_no_task_id(self):
        """Test storing agent response without task_id (no state update)."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.create_message.return_value = MagicMock()

            service._store_agent_response(None, "Hello", "test-endpoint")

            mock_db.create_message.assert_called_once()
            mock_db.update_task_state.assert_not_called()


class TestStoreErrorResponse:
    """Test class for _store_error_response method."""

    def test_store_error_response(self):
        """Test storing error response."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.create_message.return_value = MagicMock()
            mock_db.update_task_state.return_value = MagicMock()

            service._store_error_response("task_123", "Something went wrong", "test-endpoint")

            mock_db.create_message.assert_called_once()
            call_kwargs = mock_db.create_message.call_args.kwargs
            assert call_kwargs["role"] == "ROLE_AGENT"
            assert "Error: Something went wrong" in call_kwargs["parts"][0]["text"]
            assert call_kwargs["metadata"]["error"] is True

            mock_db.update_task_state.assert_called_once()
            call_kwargs = mock_db.update_task_state.call_args.kwargs
            assert call_kwargs["task_state"] == "TASK_STATE_FAILED"

    def test_store_error_response_no_task_id(self):
        """Test storing error response without task_id."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.create_message.return_value = MagicMock()

            service._store_error_response(None, "Error message", "test-endpoint")

            mock_db.create_message.assert_called_once()
            mock_db.update_task_state.assert_not_called()


class TestCollectStreamText:
    """Test class for _collect_stream_text method."""

    @pytest.mark.asyncio
    async def test_collect_stream_text_success(self):
        """Test collecting text from stream response."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        chunks = [
            'data: {"content": "Hello"}',
            'data: {"content": " World"}',
            'data: {"content": "!"}'
        ]

        mock_stream = MagicMock()
        mock_stream.body_iterator = AsyncMockIterator(chunks)

        with patch.object(service.adapter, "extract_stream_chunk", side_effect=["Hello", " World", "!"]):
            result = await service._collect_stream_text(mock_stream)

            assert result == "Hello World!"

    @pytest.mark.asyncio
    async def test_collect_stream_text_with_bytes(self):
        """Test collecting text from stream with bytes chunks."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        chunks = [b'data: {"content": "Test"}']

        mock_stream = MagicMock()
        mock_stream.body_iterator = AsyncMockIterator(chunks)

        with patch.object(service.adapter, "extract_stream_chunk", return_value="Test"):
            result = await service._collect_stream_text(mock_stream)

            assert result == "Test"

    @pytest.mark.asyncio
    async def test_collect_stream_text_skips_invalid_json(self):
        """Test collecting text skips invalid JSON."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        chunks = [
            'data: {"content": "Valid"}',
            'data: invalid json',
            'data: {"content": "More"}'
        ]

        mock_stream = MagicMock()
        mock_stream.body_iterator = AsyncMockIterator(chunks)

        with patch.object(service.adapter, "extract_stream_chunk", side_effect=["Valid", "More"]):
            result = await service._collect_stream_text(mock_stream)

            assert result == "ValidMore"

    @pytest.mark.asyncio
    async def test_collect_stream_text_skips_empty_data(self):
        """Test collecting text skips empty data."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()

        chunks = [
            'data: {"content": "Start"}',
            'data: ',
            'data: {"content": "End"}'
        ]

        mock_stream = MagicMock()
        mock_stream.body_iterator = AsyncMockIterator(chunks)

        with patch.object(service.adapter, "extract_stream_chunk", side_effect=["Start", "End"]):
            result = await service._collect_stream_text(mock_stream)

            assert result == "StartEnd"


class TestHandleMessageSendValidation:
    """Test class for handle_message_send validation."""

    @pytest.mark.asyncio
    async def test_handle_message_send_endpoint_not_found(self):
        """Test handle_message_send when endpoint not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            EndpointNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = None

            with pytest.raises(EndpointNotFoundError):
                await service.handle_message_send(
                    endpoint_id="nonexistent",
                    message={"message": {"parts": []}}
                )

    @pytest.mark.asyncio
    async def test_handle_message_send_agent_disabled(self):
        """Test handle_message_send when agent is disabled."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            AgentNotEnabledError
        )

        service = A2AServerService()

        mock_server_agent = {
            "endpoint_id": "test-endpoint",
            "agent_id": 1,
            "is_enabled": False
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_server_agent

            with pytest.raises(AgentNotEnabledError):
                await service.handle_message_send(
                    endpoint_id="test-endpoint",
                    message={"message": {"parts": []}}
                )


class TestHandleMessageStreamValidation:
    """Test class for handle_message_stream validation."""

    @pytest.mark.asyncio
    async def test_handle_message_stream_endpoint_not_found(self):
        """Test handle_message_stream when endpoint not found."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            EndpointNotFoundError
        )

        service = A2AServerService()

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = None

            with pytest.raises(EndpointNotFoundError):
                events = []
                async for event in service.handle_message_stream(
                    endpoint_id="nonexistent",
                    message={"message": {"parts": []}}
                ):
                    events.append(event)

    @pytest.mark.asyncio
    async def test_handle_message_stream_agent_disabled(self):
        """Test handle_message_stream when agent is disabled."""
        from backend.services.a2a_server_service import (
            A2AServerService,
            AgentNotEnabledError
        )

        service = A2AServerService()

        mock_server_agent = {
            "endpoint_id": "test-endpoint",
            "agent_id": 1,
            "is_enabled": False
        }

        with patch("backend.services.a2a_server_service.a2a_agent_db") as mock_db:
            mock_db.get_server_agent_by_endpoint.return_value = mock_server_agent

            with pytest.raises(AgentNotEnabledError):
                events = []
                async for event in service.handle_message_stream(
                    endpoint_id="test-endpoint",
                    message={"message": {"parts": []}}
                ):
                    events.append(event)


class TestHelperFunctions:
    """Test class for helper functions."""

    def test_generate_task_id(self):
        """Test _generate_task_id produces valid IDs."""
        from backend.services.a2a_server_service import _generate_task_id

        task_id = _generate_task_id()

        assert task_id.startswith("task_")
        assert len(task_id) > 5

    def test_generate_task_id_unique(self):
        """Test _generate_task_id produces unique IDs."""
        from backend.services.a2a_server_service import _generate_task_id

        ids = set()
        for _ in range(100):
            ids.add(_generate_task_id())

        assert len(ids) == 100

    def test_generate_endpoint_id(self):
        """Test _generate_endpoint_id produces valid IDs."""
        from backend.services.a2a_server_service import _generate_endpoint_id

        endpoint_id = _generate_endpoint_id(agent_id=123)

        assert endpoint_id.startswith("a2a_123_")
        assert len(endpoint_id) > 10

    def test_generate_endpoint_id_unique(self):
        """Test _generate_endpoint_id produces unique IDs."""
        from backend.services.a2a_server_service import _generate_endpoint_id

        ids = set()
        for _ in range(100):
            ids.add(_generate_endpoint_id(agent_id=1))

        assert len(ids) == 100


# Helper class for async iterator mock
class AsyncMockIterator:
    """Helper class to create async iterator from a list."""

    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item
