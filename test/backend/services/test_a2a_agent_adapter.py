"""
Unit tests for A2A Agent Adapter.

Tests the A2AAgentAdapter class in backend/services/a2a_agent_adapter.py.
"""
import pytest
from unittest.mock import MagicMock, patch
import json

from backend.services.a2a_agent_adapter import (
    A2AAgentAdapter,
    A2AExecutionContext,
    a2a_agent_adapter,
)


class TestA2AExecutionContext:
    """Test class for A2AExecutionContext dataclass."""

    def test_required_fields(self):
        """Test required task_id and endpoint_id."""
        ctx = A2AExecutionContext(
            task_id="task-123",
            endpoint_id="endpoint-456"
        )
        assert ctx.task_id == "task-123"
        assert ctx.endpoint_id == "endpoint-456"

    def test_optional_fields(self):
        """Test optional fields with defaults."""
        ctx = A2AExecutionContext(
            task_id="task-123",
            endpoint_id="endpoint-456",
            token_id=123,
            user_id="user-1",
            tenant_id="tenant-1",
            correlation_id="corr-1",
            metadata={"key": "value"},
            is_debug=True
        )
        assert ctx.token_id == 123
        assert ctx.user_id == "user-1"
        assert ctx.is_debug is True

    def test_default_values(self):
        """Test default values for optional fields."""
        ctx = A2AExecutionContext(
            task_id="task-123",
            endpoint_id="endpoint-456"
        )
        assert ctx.token_id is None
        assert ctx.user_id is None
        assert ctx.tenant_id is None
        assert ctx.correlation_id is None
        assert ctx.metadata == {}
        assert ctx.is_debug is False


class TestA2AAgentAdapterInit:
    """Test class for A2AAgentAdapter initialization."""

    def test_initialization(self):
        """Test adapter can be instantiated."""
        adapter = A2AAgentAdapter()
        assert adapter is not None

    def test_singleton_instance_exists(self):
        """Test that singleton instance exists."""
        assert a2a_agent_adapter is not None
        assert isinstance(a2a_agent_adapter, A2AAgentAdapter)


class TestBuildAgentRequest:
    """Test class for build_agent_request method."""

    def test_build_request_with_text_parts(self):
        """Test building request from A2A message with text parts."""
        adapter = A2AAgentAdapter()
        context = A2AExecutionContext(
            task_id="task-123",
            endpoint_id="endpoint-456",
            is_debug=True
        )

        a2a_message = {
            "message": {
                "role": "ROLE_USER",
                "parts": [{"type": "text", "text": "Hello, how are you?"}]
            }
        }

        result = adapter.build_agent_request(a2a_message, context, agent_id=1)

        assert result["agent_id"] == 1
        assert result["query"] == "Hello, how are you?"
        assert result["task_id"] == "task-123"
        assert result["is_debug"] is True
        assert "history" in result

    def test_build_request_with_empty_parts(self):
        """Test building request with empty parts list."""
        adapter = A2AAgentAdapter()
        context = A2AExecutionContext(
            task_id="task-123",
            endpoint_id="endpoint-456"
        )

        a2a_message = {
            "message": {
                "role": "ROLE_USER",
                "parts": []
            }
        }

        result = adapter.build_agent_request(a2a_message, context, agent_id=1)
        assert result["query"] == ""

    def test_build_request_with_history(self):
        """Test building request with message history."""
        adapter = A2AAgentAdapter()
        context = A2AExecutionContext(
            task_id="task-123",
            endpoint_id="endpoint-456"
        )

        a2a_message = {
            "message": {
                "role": "ROLE_USER",
                "parts": [{"type": "text", "text": "Follow-up question"}]
            },
            "history": [
                {"role": "ROLE_USER", "parts": [{"type": "text", "text": "Previous question"}]},
                {"role": "ROLE_AGENT", "parts": [{"type": "text", "text": "Previous answer"}]}
            ]
        }

        result = adapter.build_agent_request(a2a_message, context, agent_id=1)

        assert len(result["history"]) == 2
        assert result["history"][0]["role"] == "user"
        assert result["history"][0]["content"] == "Previous question"
        assert result["history"][1]["role"] == "assistant"
        assert result["history"][1]["content"] == "Previous answer"

    def test_build_request_with_metadata(self):
        """Test building request with correlation ID."""
        adapter = A2AAgentAdapter()
        context = A2AExecutionContext(
            task_id="task-123",
            endpoint_id="endpoint-456",
            correlation_id="corr-789",
            metadata={"source": "test"}
        )

        a2a_message = {
            "message": {
                "role": "ROLE_USER",
                "parts": [{"type": "text", "text": "Test"}]
            }
        }

        result = adapter.build_agent_request(a2a_message, context, agent_id=1)
        assert result["correlation_id"] == "corr-789"
        assert result["metadata"] == {"source": "test"}


class TestParseA2AMessage:
    """Test class for parse_a2a_message method."""

    def test_parse_json_rpc_format(self):
        """Test parsing JSON-RPC format."""
        adapter = A2AAgentAdapter()

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": "ROLE_USER",
                    "parts": [{"type": "text", "text": "Hello"}]
                }
            }
        }

        result = adapter.parse_a2a_message(payload)
        assert "message" in result
        assert result["message"]["parts"][0]["text"] == "Hello"

    def test_parse_direct_message_format(self):
        """Test parsing direct message format."""
        adapter = A2AAgentAdapter()

        payload = {
            "message": {
                "role": "ROLE_USER",
                "parts": [{"type": "text", "text": "Hello"}]
            }
        }

        result = adapter.parse_a2a_message(payload)
        assert "message" in result


class TestBuildA2ATaskResponse:
    """Test class for build_a2a_task_response method."""

    def test_basic_task_response(self):
        """Test building basic task response."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_task_response(
            task_id="task-123",
            status="completed"
        )

        assert "task" in result
        assert result["task"]["id"] == "task-123"
        assert result["task"]["status"]["state"] == "TASK_STATE_COMPLETED"

    def test_task_response_with_parts(self):
        """Test task response with message parts."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_task_response(
            task_id="task-123",
            status="completed",
            parts=[{"type": "text", "text": "Response text", "mediaType": "text/plain"}]
        )

        assert result["task"]["status"]["message"]["role"] == "ROLE_AGENT"
        assert len(result["task"]["status"]["message"]["parts"]) == 1

    def test_task_response_with_context_id(self):
        """Test task response with context ID."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_task_response(
            task_id="task-123",
            status="working",
            context_id="ctx-456"
        )

        assert result["task"]["contextId"] == "ctx-456"

    def test_task_response_with_artifacts(self):
        """Test task response with artifacts."""
        adapter = A2AAgentAdapter()

        artifacts = [
            {"parts": [{"type": "text", "text": "Artifact content"}]}
        ]

        result = adapter.build_a2a_task_response(
            task_id="task-123",
            status="completed",
            artifacts=artifacts
        )

        assert "artifacts" in result["task"]
        assert len(result["task"]["artifacts"]) == 1

    def test_task_response_state_mapping(self):
        """Test state mapping from short to TASK_STATE format."""
        adapter = A2AAgentAdapter()

        test_cases = [
            ("working", "TASK_STATE_WORKING"),
            ("completed", "TASK_STATE_COMPLETED"),
            ("failed", "TASK_STATE_FAILED"),
            ("canceled", "TASK_STATE_CANCELED"),
            ("input_required", "TASK_STATE_INPUT_REQUIRED"),
            ("rejected", "TASK_STATE_REJECTED"),
            ("auth_required", "TASK_STATE_AUTH_REQUIRED"),
        ]

        for short_state, expected_state in test_cases:
            result = adapter.build_a2a_task_response(
                task_id="task-123",
                status=short_state
            )
            assert result["task"]["status"]["state"] == expected_state

    def test_task_response_with_custom_timestamp(self):
        """Test task response with custom timestamp."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_task_response(
            task_id="task-123",
            status="completed",
            timestamp="2024-01-01T00:00:00Z"
        )

        assert result["task"]["status"]["timestamp"] == "2024-01-01T00:00:00Z"


class TestBuildA2AMessageResponse:
    """Test class for build_a2a_message_response method."""

    def test_basic_message_response(self):
        """Test building basic message response."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_message_response(
            role="ROLE_AGENT",
            text="Hello!"
        )

        assert "message" in result
        assert result["message"]["role"] == "ROLE_AGENT"
        assert result["message"]["parts"][0]["text"] == "Hello!"

    def test_message_response_generates_message_id(self):
        """Test that message ID is generated if not provided."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_message_response(
            role="ROLE_AGENT",
            text="Hello!"
        )

        assert "messageId" in result["message"]
        assert result["message"]["messageId"].startswith("msg_")

    def test_message_response_with_custom_parts(self):
        """Test message response with custom parts."""
        adapter = A2AAgentAdapter()

        custom_parts = [
            {"type": "text", "text": "Part 1"},
            {"type": "text", "text": "Part 2"}
        ]

        result = adapter.build_a2a_message_response(
            role="ROLE_AGENT",
            parts=custom_parts
        )

        assert len(result["message"]["parts"]) == 2

    def test_message_response_with_context_id(self):
        """Test message response with context ID."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_message_response(
            role="ROLE_AGENT",
            text="Hello!",
            context_id="ctx-456"
        )

        assert result["message"]["contextId"] == "ctx-456"

    def test_message_response_with_task_id(self):
        """Test message response with task ID."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_message_response(
            role="ROLE_AGENT",
            text="Hello!",
            task_id="task-123"
        )

        assert result["message"]["taskId"] == "task-123"


class TestBuildA2ATaskEvent:
    """Test class for build_a2a_task_event method."""

    def test_task_progress_event(self):
        """Test building task progress event."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_task_event(
            task_id="task-123",
            event_type="taskProgress",
            data={
                "content": "Working on it...",
                "lastChunk": False
            }
        )

        assert "artifactUpdate" in result
        assert result["artifactUpdate"]["taskId"] == "task-123"
        assert "artifact" in result["artifactUpdate"]

    def test_task_status_update_event(self):
        """Test building task status update event."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_task_event(
            task_id="task-123",
            event_type="taskStatusUpdate",
            data={
                "status": {
                    "state": "TASK_STATE_WORKING"
                }
            }
        )

        assert "statusUpdate" in result
        assert result["statusUpdate"]["taskId"] == "task-123"
        assert "status" in result["statusUpdate"]

    def test_task_artifact_event(self):
        """Test building task artifact event."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_task_event(
            task_id="task-123",
            event_type="taskArtifact",
            data={
                "artifact": {"parts": [{"type": "text", "text": "File content"}]},
                "append": True,
                "lastChunk": False
            }
        )

        assert "artifactUpdate" in result
        assert "artifact" in result["artifactUpdate"]

    def test_task_event_with_context_id(self):
        """Test task event with context ID."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_task_event(
            task_id="task-123",
            event_type="taskStatusUpdate",
            data={"status": {"state": "TASK_STATE_WORKING"}},
            context_id="ctx-456"
        )

        assert result["statusUpdate"]["contextId"] == "ctx-456"

    def test_unknown_event_type_returns_default(self):
        """Test unknown event type returns default task."""
        adapter = A2AAgentAdapter()

        result = adapter.build_a2a_task_event(
            task_id="task-123",
            event_type="unknownEvent",
            data={}
        )

        assert "task" in result
        assert result["task"]["id"] == "task-123"


class TestExtractStreamChunk:
    """Test class for extract_stream_chunk method."""

    def test_extract_text_type(self):
        """Test extracting from text type chunk."""
        adapter = A2AAgentAdapter()

        chunk = {"type": "text", "content": "Hello"}
        result = adapter.extract_stream_chunk(chunk)
        assert result == "Hello"

    def test_extract_message_type(self):
        """Test extracting from message type chunk."""
        adapter = A2AAgentAdapter()

        chunk = {"type": "message", "content": "Hello"}
        result = adapter.extract_stream_chunk(chunk)
        assert result == "Hello"

    def test_extract_answer_type(self):
        """Test extracting from answer type chunk."""
        adapter = A2AAgentAdapter()

        chunk = {"type": "answer", "answer": "The answer is 42"}
        result = adapter.extract_stream_chunk(chunk)
        assert result == "The answer is 42"

    def test_extract_direct_content(self):
        """Test extracting from direct content field."""
        adapter = A2AAgentAdapter()

        chunk = {"content": "Direct content"}
        result = adapter.extract_stream_chunk(chunk)
        assert result == "Direct content"

    def test_extract_returns_none_for_empty(self):
        """Test returns None when no content."""
        adapter = A2AAgentAdapter()

        chunk = {"type": "unknown"}
        result = adapter.extract_stream_chunk(chunk)
        assert result is None


class TestIsTerminalChunk:
    """Test class for is_terminal_chunk method."""

    def test_terminal_done(self):
        """Test done type is terminal."""
        adapter = A2AAgentAdapter()

        assert adapter.is_terminal_chunk({"type": "done"}) is True

    def test_terminal_end(self):
        """Test end type is terminal."""
        adapter = A2AAgentAdapter()

        assert adapter.is_terminal_chunk({"type": "end"}) is True

    def test_terminal_stop(self):
        """Test stop type is terminal."""
        adapter = A2AAgentAdapter()

        assert adapter.is_terminal_chunk({"type": "stop"}) is True

    def test_terminal_final(self):
        """Test final type is terminal."""
        adapter = A2AAgentAdapter()

        assert adapter.is_terminal_chunk({"type": "final"}) is True

    def test_terminal_completed_status(self):
        """Test completed status is terminal."""
        adapter = A2AAgentAdapter()

        assert adapter.is_terminal_chunk({"status": "completed"}) is True

    def test_terminal_failed_status(self):
        """Test failed status is terminal."""
        adapter = A2AAgentAdapter()

        assert adapter.is_terminal_chunk({"status": "failed"}) is True

    def test_non_terminal_chunk(self):
        """Test non-terminal chunk returns False."""
        adapter = A2AAgentAdapter()

        assert adapter.is_terminal_chunk({"type": "text", "content": "Hello"}) is False


class TestParseTaskStatus:
    """Test class for parse_task_status method."""

    def test_parse_explicit_state(self):
        """Test parsing explicit state field."""
        adapter = A2AAgentAdapter()

        result = adapter.parse_task_status({"state": "TASK_STATE_COMPLETED"})
        assert result == "TASK_STATE_COMPLETED"

    def test_parse_nested_status(self):
        """Test parsing nested status field."""
        adapter = A2AAgentAdapter()

        result = adapter.parse_task_status(
            {"status": {"state": "TASK_STATE_WORKING"}}
        )
        assert result == "TASK_STATE_WORKING"

    def test_parse_string_status(self):
        """Test parsing string status."""
        adapter = A2AAgentAdapter()

        result = adapter.parse_task_status("completed")
        assert result == "completed"

    def test_parse_unknown_defaults_to_working(self):
        """Test unknown status defaults to working."""
        adapter = A2AAgentAdapter()

        result = adapter.parse_task_status({})
        assert result == "working"

    def test_parse_nested_string_status(self):
        """Test parsing nested string status."""
        adapter = A2AAgentAdapter()

        result = adapter.parse_task_status(
            {"status": "working"}
        )
        assert result == "working"


class TestMapTaskState:
    """Test class for _map_task_state method."""

    def test_already_mapped_state(self):
        """Test state already with TASK_STATE_ prefix."""
        adapter = A2AAgentAdapter()

        assert adapter._map_task_state("TASK_STATE_WORKING") == "TASK_STATE_WORKING"

    def test_short_state_mapping(self):
        """Test short state to TASK_STATE mapping."""
        adapter = A2AAgentAdapter()

        test_cases = [
            ("working", "TASK_STATE_WORKING"),
            ("completed", "TASK_STATE_COMPLETED"),
            ("failed", "TASK_STATE_FAILED"),
            ("canceled", "TASK_STATE_CANCELED"),
        ]

        for short_state, expected in test_cases:
            assert adapter._map_task_state(short_state) == expected

    def test_unknown_state_uppercased(self):
        """Test unknown state gets TASK_STATE_ prefix."""
        adapter = A2AAgentAdapter()

        result = adapter._map_task_state("custom_state")
        assert result == "TASK_STATE_CUSTOM_STATE"


class TestBuildHistory:
    """Test class for _build_history method."""

    def test_empty_history(self):
        """Test empty history returns empty list."""
        adapter = A2AAgentAdapter()

        result = adapter._build_history({})
        assert result == []

    def test_role_user_to_user(self):
        """Test ROLE_USER maps to internal user role."""
        adapter = A2AAgentAdapter()

        a2a_message = {
            "history": [
                {"role": "ROLE_USER", "parts": [{"type": "text", "text": "Hello"}]}
            ]
        }

        result = adapter._build_history(a2a_message)
        assert result[0]["role"] == "user"

    def test_role_agent_to_assistant(self):
        """Test ROLE_AGENT maps to internal assistant role."""
        adapter = A2AAgentAdapter()

        a2a_message = {
            "history": [
                {"role": "ROLE_AGENT", "parts": [{"type": "text", "text": "Hi there"}]}
            ]
        }

        result = adapter._build_history(a2a_message)
        assert result[0]["role"] == "assistant"

    def test_unknown_role_defaults_to_user(self):
        """Test unknown role defaults to user."""
        adapter = A2AAgentAdapter()

        a2a_message = {
            "history": [
                {"role": "ROLE_UNKNOWN", "parts": [{"type": "text", "text": "?"}]}
            ]
        }

        result = adapter._build_history(a2a_message)
        assert result[0]["role"] == "user"

    def test_empty_parts(self):
        """Test handling of empty parts list."""
        adapter = A2AAgentAdapter()

        a2a_message = {
            "history": [
                {"role": "ROLE_USER", "parts": []}
            ]
        }

        result = adapter._build_history(a2a_message)
        assert result[0]["content"] == ""

    def test_non_dict_part(self):
        """Test handling of non-dict parts."""
        adapter = A2AAgentAdapter()

        a2a_message = {
            "history": [
                {"role": "ROLE_USER", "parts": ["string part"]}
            ]
        }

        result = adapter._build_history(a2a_message)
        assert result[0]["content"] == "string part"
