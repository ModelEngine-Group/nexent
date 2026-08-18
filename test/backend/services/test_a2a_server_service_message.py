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
        """Test collecting stream text skips empty data."""
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

    @pytest.mark.asyncio
    async def test_collect_stream_events_preserves_raw_event_objects(self):
        """Test collecting stream events preserves event fields and order."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()
        first_event = {"type": "model_output_thinking", "content": "internal"}
        second_event = {"type": "final_answer", "content": "answer"}
        mock_stream = MagicMock()
        mock_stream.body_iterator = AsyncMockIterator([
            f"data: {json.dumps(first_event)}\n\n",
            f"data: {json.dumps(second_event)}\n\n",
        ])

        result = await service._collect_stream_events(mock_stream)

        assert result == [first_event, second_event]

    def test_build_agent_run_event_parts_keeps_each_event_separate(self):
        """Test each raw event becomes a separate JSON data part."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()
        events = [
            {"type": "model_output_thinking", "content": "internal"},
            {"type": "final_answer", "content": "answer"},
        ]

        result = service._build_agent_run_event_parts(events)

        assert [part["data"] for part in result] == events
        assert all(part["mediaType"] == "application/json" for part in result)

    def test_coalesce_consecutive_events_with_same_type(self):
        """Test adjacent same-type string events are combined."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()
        events = [
            {"type": "model_output_deep_thinking", "content": "我们"},
            {"type": "model_output_deep_thinking", "content": "需要"},
            {"type": "step_count", "content": "\n**步骤 1** \n"},
            {"type": "model_output_deep_thinking", "content": "搜索"},
        ]

        assert service._coalesce_consecutive_events(events) == [
            {"type": "model_output_deep_thinking", "content": "我们需要"},
            {"type": "step_count", "content": "\n**步骤 1** \n"},
            {"type": "model_output_deep_thinking", "content": "搜索"},
        ]

    def test_coalesce_does_not_merge_events_with_different_metadata(self):
        """Test same-type events with different metadata stay separate."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()
        events = [
            {"type": "model_output_deep_thinking", "step": 1, "content": "a"},
            {"type": "model_output_deep_thinking", "step": 2, "content": "b"},
        ]

        assert service._coalesce_consecutive_events(events) == events

    def test_coalesce_does_not_merge_non_string_content(self):
        """Test events with structured content stay separate."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()
        events = [
            {"type": "tool", "content": {"name": "search"}},
            {"type": "tool", "content": {"name": "search"}},
        ]

        assert service._coalesce_consecutive_events(events) == events

    def test_extract_final_answer_ignores_non_final_events(self):
        """Test only final_answer events are used for persistence text."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()
        events = [
            {"type": "model_output_thinking", "content": "internal"},
            {"type": "final_answer", "content": "first"},
            {"type": "final_answer", "content": "second"},
        ]

        assert service._extract_final_answer(events) == "firstsecond"

    @pytest.mark.asyncio
    async def test_collect_stream_events_skips_non_sse_and_non_dict_payloads(self):
        """Test event collection handles bytes, empty data, invalid JSON, and non-dicts."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()
        valid_event = {"type": "final_answer", "content": "done"}
        mock_stream = MagicMock()
        mock_stream.body_iterator = AsyncMockIterator([
            b"event: ignored\n\n",
            "data: ",
            "data: invalid json",
            "data: [1, 2, 3]",
            f"data: {json.dumps(valid_event)}\n\n",
        ])

        assert await service._collect_stream_events(mock_stream) == [valid_event]


class TestHandleMessageSend:
    """Test successful message:send execution paths."""

    @pytest.mark.asyncio
    async def test_handle_message_send_persists_events_and_builds_message_response(self):
        """Test simple requests persist the final answer and expose raw events."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()
        server_agent = {"agent_id": 7, "tenant_id": "agent-tenant", "is_enabled": True}
        parsed_message = {"message": {"parts": [{"type": "text", "text": "hello"}]}}
        events = [
            {"type": "model_output_thinking", "content": "working"},
            {"type": "final_answer", "content": "done"},
        ]
        stream_response = MagicMock(body_iterator=AsyncMockIterator([
            f"data: {json.dumps(events[0])}\n\n",
            f"data: {json.dumps(events[1])}\n\n",
        ]))

        with patch.object(service, "_validate_endpoint", return_value=server_agent), \
                patch.object(service.adapter, "parse_a2a_message", return_value=parsed_message), \
                patch.object(service, "_resolve_task_id", return_value=(None, None, False)), \
                patch.object(service, "_store_user_message"), \
                patch.object(service, "_store_agent_response") as store_response, \
                patch.object(service.adapter, "build_agent_request", return_value={
                    "agent_id": 7, "query": "hello", "history": [], "is_debug": True
                }), \
                patch.object(service.adapter, "build_a2a_message_response", return_value={"ok": True}) as build_response, \
                patch("services.agent_service.run_agent_stream", new_callable=AsyncMock, return_value=stream_response) as run_stream:
            result = await service.handle_message_send("endpoint-1", {"message": {}})

        assert result == {"ok": True}
        store_response.assert_called_once_with(None, "done", "endpoint-1")
        build_response.assert_called_once()
        assert build_response.call_args.kwargs["text"] is None
        assert [part["data"] for part in build_response.call_args.kwargs["parts"]] == events
        runtime_scope_id = run_stream.await_args.kwargs["runtime_scope_id"]
        assert runtime_scope_id.startswith("a2a:")
        assert runtime_scope_id != "a2a:simple"

    @pytest.mark.asyncio
    async def test_handle_message_send_complex_request_builds_task_response(self):
        """Test complex requests return a completed task with coalesced event parts."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()
        server_agent = {"agent_id": 7, "is_enabled": True}
        parsed_message = {"message": {"parts": []}, "history": [{"role": "user"}]}
        stream_response = MagicMock(body_iterator=AsyncMockIterator([
            'data: {"type": "final_answer", "content": "A"}',
            'data: {"type": "final_answer", "content": "B"}',
        ]))

        with patch.object(service, "_validate_endpoint", return_value=server_agent), \
                patch.object(service.adapter, "parse_a2a_message", return_value=parsed_message), \
                patch.object(service, "_resolve_task_id", return_value=("task-1", "ctx-1", True)), \
                patch.object(service, "_store_user_message"), \
                patch.object(service, "_store_agent_response") as store_response, \
                patch.object(service.adapter, "build_agent_request", return_value={
                    "agent_id": 7, "query": "", "history": [], "is_debug": True
                }), \
                patch.object(service.adapter, "build_a2a_task_response", return_value={"task": True}) as build_response, \
                patch("services.agent_service.run_agent_stream", new_callable=AsyncMock, return_value=stream_response) as run_stream:
            result = await service.handle_message_send("endpoint-1", {"message": {}})

        assert result == {"task": True}
        store_response.assert_called_once_with("task-1", "AB", "endpoint-1")
        parts = build_response.call_args.kwargs["parts"]
        assert parts == [{"data": {"type": "final_answer", "content": "AB"}, "mediaType": "application/json"}]
        assert run_stream.await_args.kwargs["runtime_scope_id"] == "a2a:task-1"

    @pytest.mark.asyncio
    async def test_handle_message_send_maps_runtime_interruption_to_failed_response(self):
        """A runtime interruption must not be persisted as a completed A2A response."""
        from backend.services.a2a_server_service import A2AServerService, RUN_INTERRUPTED_MESSAGE

        service = A2AServerService()
        server_agent = {"agent_id": 7, "tenant_id": "agent-tenant", "is_enabled": True}
        interrupted_event = {
            "type": "error",
            "status": "run_interrupted",
            "code": "run_interrupted",
        }
        stream_response = MagicMock(body_iterator=AsyncMockIterator([
            f"data: {json.dumps(interrupted_event)}\n\n",
        ]))

        with patch.object(service, "_validate_endpoint", return_value=server_agent), \
                patch.object(service.adapter, "parse_a2a_message", return_value={"message": {"parts": []}}), \
                patch.object(service, "_resolve_task_id", return_value=("task-1", "ctx-1", True)), \
                patch.object(service, "_store_user_message"), \
                patch.object(service, "_store_agent_response") as store_response, \
                patch.object(service, "_store_error_response") as store_error, \
                patch.object(service.adapter, "build_agent_request", return_value={
                    "agent_id": 7, "query": "", "history": [], "is_debug": True
                }), \
                patch.object(service.adapter, "build_a2a_message_response", return_value={"failed": True}), \
                patch("services.agent_service.run_agent_stream", new_callable=AsyncMock, return_value=stream_response):
            result = await service.handle_message_send("endpoint-1", {"message": {}})

        assert result == {"failed": True}
        store_response.assert_not_called()
        store_error.assert_called_once_with("task-1", RUN_INTERRUPTED_MESSAGE, "endpoint-1")


class TestHandleMessageStream:
    """Test successful message:stream execution paths."""

    @pytest.mark.asyncio
    async def test_handle_message_stream_filters_chunks_and_stores_final_answer(self):
        """Test streaming yields valid event artifacts and terminal status events."""
        from backend.services.a2a_server_service import A2AServerService

        service = A2AServerService()
        server_agent = {"agent_id": 7, "tenant_id": "agent-tenant", "is_enabled": True}
        parsed_message = {"message": {"parts": []}}
        valid_event = {"type": "final_answer", "content": "done"}
        stream_response = MagicMock(body_iterator=AsyncMockIterator([
            b"comment\n",
            b"data: invalid json",
            b"data: [1, 2]",
            f"data: {json.dumps(valid_event)}",
        ]))

        with patch.object(service, "_validate_endpoint", return_value=server_agent), \
                patch.object(service.adapter, "parse_a2a_message", return_value=parsed_message), \
                patch.object(service, "_resolve_task_id", return_value=("task-1", "ctx-1", True)), \
                patch.object(service, "_store_user_message"), \
                patch.object(service, "_store_agent_response") as store_response, \
                patch.object(service.adapter, "build_agent_request", return_value={
                    "agent_id": 7, "query": "", "history": [], "is_debug": True
                }), \
                patch.object(service.adapter, "build_a2a_task_event", side_effect=lambda **kwargs: kwargs), \
                patch("services.agent_service.run_agent_stream", new_callable=AsyncMock, return_value=stream_response) as run_stream:
            result = [event async for event in service.handle_message_stream("endpoint-1", {"message": {}})]

        assert result[0]["event_type"] == "taskStatusUpdate"
        assert result[1]["data"]["artifact"]["parts"] == [
            {"data": valid_event, "mediaType": "application/json"}
        ]
        assert result[-2]["data"]["lastChunk"] is True
        assert result[-1]["data"]["status"]["state"] == "TASK_STATE_COMPLETED"
        store_response.assert_called_once_with("task-1", "done", "endpoint-1")
        assert run_stream.await_args.kwargs["runtime_scope_id"] == "a2a:task-1"

    @pytest.mark.asyncio
    async def test_handle_message_stream_ends_failed_on_runtime_interruption(self):
        """A streamed runtime interruption must end the A2A task as failed."""
        from backend.services.a2a_server_service import A2AServerService, RUN_INTERRUPTED_MESSAGE

        service = A2AServerService()
        server_agent = {"agent_id": 7, "tenant_id": "agent-tenant", "is_enabled": True}
        interrupted_event = {
            "type": "error",
            "status": "run_interrupted",
            "code": "run_interrupted",
        }
        stream_response = MagicMock(body_iterator=AsyncMockIterator([
            f"data: {json.dumps(interrupted_event)}",
        ]))

        with patch.object(service, "_validate_endpoint", return_value=server_agent), \
                patch.object(service.adapter, "parse_a2a_message", return_value={"message": {"parts": []}}), \
                patch.object(service, "_resolve_task_id", return_value=("task-1", "ctx-1", True)), \
                patch.object(service, "_store_user_message"), \
                patch.object(service, "_store_agent_response") as store_response, \
                patch.object(service, "_store_error_response") as store_error, \
                patch.object(service.adapter, "build_agent_request", return_value={
                    "agent_id": 7, "query": "", "history": [], "is_debug": True
                }), \
                patch.object(service.adapter, "build_a2a_task_event", side_effect=lambda **kwargs: kwargs), \
                patch("services.agent_service.run_agent_stream", new_callable=AsyncMock, return_value=stream_response):
            result = [event async for event in service.handle_message_stream("endpoint-1", {"message": {}})]

        assert result[-1]["data"]["status"]["state"] == "TASK_STATE_FAILED"
        store_response.assert_not_called()
        store_error.assert_called_once_with("task-1", RUN_INTERRUPTED_MESSAGE, "endpoint-1")


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
