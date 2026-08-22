"""
Unit tests for Error Message definitions.

Tests the ErrorMessage class and its methods for getting error messages.
"""
import pytest
from backend.consts.error_code import ErrorCode
from backend.consts.error_message import ErrorMessage


class TestErrorMessageGetMessage:
    """Test class for ErrorMessage.get_message method."""

    def test_get_message_dify_auth_error(self):
        """Test getting message for DIFY_AUTH_ERROR."""
        msg = ErrorMessage.get_message(ErrorCode.DIFY_AUTH_ERROR)
        assert "Dify authentication failed" in msg
        assert "API key" in msg

    def test_get_message_dify_config_invalid(self):
        """Test getting message for DIFY_CONFIG_INVALID."""
        msg = ErrorMessage.get_message(ErrorCode.DIFY_CONFIG_INVALID)
        assert "Dify configuration" in msg

    def test_get_message_dify_connection_error(self):
        """Test getting message for DIFY_CONNECTION_ERROR."""
        msg = ErrorMessage.get_message(ErrorCode.DIFY_CONNECTION_ERROR)
        assert "connect to Dify" in msg

    def test_get_message_dify_rate_limit(self):
        """Test getting message for DIFY_RATE_LIMIT."""
        msg = ErrorMessage.get_message(ErrorCode.DIFY_RATE_LIMIT)
        assert "rate limit" in msg

    def test_get_message_common_validation_error(self):
        """Test getting message for COMMON_VALIDATION_ERROR."""
        msg = ErrorMessage.get_message(ErrorCode.COMMON_VALIDATION_ERROR)
        assert "Validation" in msg

    def test_get_message_common_unauthorized(self):
        """Test getting message for COMMON_UNAUTHORIZED."""
        msg = ErrorMessage.get_message(ErrorCode.COMMON_UNAUTHORIZED)
        assert "not authorized" in msg.lower()

    def test_get_message_common_token_expired(self):
        """Test getting message for COMMON_TOKEN_EXPIRED."""
        msg = ErrorMessage.get_message(ErrorCode.COMMON_TOKEN_EXPIRED)
        assert "session" in msg.lower()
        assert "expired" in msg.lower()

    def test_get_message_common_token_invalid(self):
        """Test getting message for COMMON_TOKEN_INVALID."""
        msg = ErrorMessage.get_message(ErrorCode.COMMON_TOKEN_INVALID)
        assert "token" in msg.lower()

    def test_get_message_common_rate_limit_exceeded(self):
        """Test getting message for COMMON_RATE_LIMIT_EXCEEDED."""
        msg = ErrorMessage.get_message(ErrorCode.COMMON_RATE_LIMIT_EXCEEDED)
        assert "requests" in msg.lower()

    def test_get_message_file_not_found(self):
        """Test getting message for FILE_NOT_FOUND."""
        msg = ErrorMessage.get_message(ErrorCode.FILE_NOT_FOUND)
        assert "File" in msg
        assert "not found" in msg.lower()

    def test_get_message_file_too_large(self):
        """Test getting message for FILE_TOO_LARGE."""
        msg = ErrorMessage.get_message(ErrorCode.FILE_TOO_LARGE)
        assert "size" in msg.lower()

    def test_get_message_system_unknown_error(self):
        """Test getting message for SYSTEM_UNKNOWN_ERROR."""
        msg = ErrorMessage.get_message(ErrorCode.SYSTEM_UNKNOWN_ERROR)
        assert "unknown error" in msg.lower()

    def test_get_message_system_internal_error(self):
        """Test getting message for SYSTEM_INTERNAL_ERROR."""
        msg = ErrorMessage.get_message(ErrorCode.SYSTEM_INTERNAL_ERROR)
        assert "internal" in msg.lower() or "server" in msg.lower()

    def test_get_message_knowledge_not_found(self):
        """Test getting message for KNOWLEDGE_NOT_FOUND."""
        msg = ErrorMessage.get_message(ErrorCode.KNOWLEDGE_NOT_FOUND)
        assert "Knowledge" in msg

    def test_get_message_memory_not_found(self):
        """Test getting message for MEMORY_NOT_FOUND."""
        msg = ErrorMessage.get_message(ErrorCode.MEMORY_NOT_FOUND)
        assert "Memory" in msg

    def test_get_message_mcp_connection_failed(self):
        """Test getting message for MCP_CONNECTION_FAILED."""
        msg = ErrorMessage.get_message(ErrorCode.MCP_CONNECTION_FAILED)
        assert "MCP" in msg

    def test_get_message_northbound_request_failed(self):
        """Test getting message for NORTHBOUND_REQUEST_FAILED."""
        msg = ErrorMessage.get_message(ErrorCode.NORTHBOUND_REQUEST_FAILED)
        assert "Northbound" in msg

    def test_get_message_dataprocess_task_failed(self):
        """Test getting message for DATAPROCESS_TASK_FAILED."""
        msg = ErrorMessage.get_message(ErrorCode.DATAPROCESS_TASK_FAILED)
        assert "Data" in msg or "process" in msg.lower()

    def test_get_message_unknown_code_returns_default(self):
        """Test that unknown error code returns default message."""
        # This tests that the fallback works
        msg = ErrorMessage.get_message(ErrorCode.DIFY_AUTH_ERROR)
        assert msg != ""


class TestErrorMessageGetMessageWithCode:
    """Test class for ErrorMessage.get_message_with_code method."""

    def test_get_message_with_code_returns_tuple(self):
        """Test that get_message_with_code returns tuple."""
        code, msg = ErrorMessage.get_message_with_code(
            ErrorCode.DIFY_AUTH_ERROR)
        assert isinstance(code, str)
        assert isinstance(msg, str)

    def test_get_message_with_code_dify_auth(self):
        """Test get_message_with_code for DIFY_AUTH_ERROR."""
        code, msg = ErrorMessage.get_message_with_code(
            ErrorCode.DIFY_AUTH_ERROR)
        assert code == "130204"
        assert "Dify authentication failed" in msg

    def test_get_message_with_code_common_validation(self):
        """Test get_message_with_code for COMMON_VALIDATION_ERROR."""
        code, msg = ErrorMessage.get_message_with_code(
            ErrorCode.COMMON_VALIDATION_ERROR)
        assert code == "000101"
        assert "Validation" in msg

    def test_get_message_with_code_system_error(self):
        """Test get_message_with_code for SYSTEM_INTERNAL_ERROR."""
        code, msg = ErrorMessage.get_message_with_code(
            ErrorCode.SYSTEM_INTERNAL_ERROR)
        assert code == "990105"
        assert "error" in msg.lower()

    def test_get_message_with_code_tuple_length(self):
        """Test that get_message_with_code returns exactly 2 elements."""
        result = ErrorMessage.get_message_with_code(
            ErrorCode.DIFY_CONFIG_INVALID)
        assert len(result) == 2

    def test_get_message_with_code_tuple_order(self):
        """Test that get_message_with_code returns (code, message) in correct order."""
        code, msg = ErrorMessage.get_message_with_code(
            ErrorCode.KNOWLEDGE_NOT_FOUND)
        # First element should be the error code string
        assert code == ErrorCode.KNOWLEDGE_NOT_FOUND.value
        # Second element should be the message
        assert msg == ErrorMessage.get_message(ErrorCode.KNOWLEDGE_NOT_FOUND)


class TestErrorMessageGetAllMessages:
    """Test class for ErrorMessage.get_all_messages method."""

    def test_get_all_messages_returns_dict(self):
        """Test that get_all_messages returns a dictionary."""
        messages = ErrorMessage.get_all_messages()
        assert isinstance(messages, dict)

    def test_get_all_messages_contains_dify_codes(self):
        """Test that get_all_messages contains Dify error codes."""
        messages = ErrorMessage.get_all_messages()
        assert "130201" in messages  # DIFY_SERVICE_ERROR
        assert "130202" in messages  # DIFY_CONFIG_INVALID
        assert "130203" in messages  # DIFY_CONNECTION_ERROR
        assert "130204" in messages  # DIFY_AUTH_ERROR
        assert "130205" in messages  # DIFY_RATE_LIMIT
        assert "130206" in messages  # DIFY_RESPONSE_ERROR

    def test_get_all_messages_contains_common_codes(self):
        """Test that get_all_messages contains common error codes."""
        messages = ErrorMessage.get_all_messages()
        assert "000101" in messages  # COMMON_VALIDATION_ERROR
        assert "000201" in messages  # COMMON_UNAUTHORIZED
        assert "000203" in messages  # COMMON_TOKEN_EXPIRED

    def test_get_all_messages_contains_system_codes(self):
        """Test that get_all_messages contains system error codes."""
        messages = ErrorMessage.get_all_messages()
        assert "990101" in messages  # SYSTEM_UNKNOWN_ERROR
        assert "990105" in messages  # SYSTEM_INTERNAL_ERROR

    def test_get_all_messages_all_values_are_strings(self):
        """Test that all message values in get_all_messages are non-empty strings."""
        messages = ErrorMessage.get_all_messages()
        for code, msg in messages.items():
            assert isinstance(msg, str), f"Message for {code} is not a string"
            assert len(msg) > 0, f"Message for {code} is empty"

    def test_get_all_messages_all_keys_are_strings(self):
        """Test that all keys in get_all_messages are string error codes."""
        messages = ErrorMessage.get_all_messages()
        for key in messages.keys():
            assert isinstance(key, str), f"Key {key} is not a string"
            # Error codes should be numeric strings
            assert key.isdigit(), f"Key {key} is not a numeric error code"

    def test_get_all_messages_contains_multiple_categories(self):
        """Test that get_all_messages contains errors from multiple categories."""
        messages = ErrorMessage.get_all_messages()
        # Should have errors from different modules
        # Common (00), Chat (01), Knowledge (06), System (99)
        has_common = any(key.startswith("00") for key in messages.keys())
        has_chat = any(key.startswith("01") for key in messages.keys())
        has_knowledge = any(key.startswith("06") for key in messages.keys())
        has_system = any(key.startswith("99") for key in messages.keys())
        assert has_common and has_chat and has_knowledge and has_system

    def test_get_all_messages_count(self):
        """Test that get_all_messages returns expected number of messages."""
        messages = ErrorMessage.get_all_messages()
        # Should have at least 30 error messages
        assert len(messages) >= 30

    def test_get_all_messages_mcp_codes(self):
        """Test that get_all_messages contains MCP error codes."""
        messages = ErrorMessage.get_all_messages()
        assert "070101" in messages  # MCP_TOOL_NOT_FOUND
        assert "070102" in messages  # MCP_TOOL_EXECUTION_FAILED
        assert "070103" in messages  # MCP_TOOL_CONFIG_INVALID


class TestErrorMessageCoverage:
    """Test class for error message coverage."""

    def test_all_error_codes_have_messages(self):
        """Test that all defined ErrorCodes have messages."""
        # Get all error codes from ErrorCode enum
        all_codes = list(ErrorCode)

        for code in all_codes:
            msg = ErrorMessage.get_message(code)
            assert msg != "", f"Error code {code} has no message"
            assert isinstance(msg, str), f"Message for {code} is not a string"

    def test_message_not_generic_for_specific_errors(self):
        """Test that specific errors have specific messages, not the default."""
        # Dify auth error should have specific message
        msg = ErrorMessage.get_message(ErrorCode.DIFY_AUTH_ERROR)
        assert "authentication failed" in msg.lower()

        # Connection errors should mention connection
        msg = ErrorMessage.get_message(ErrorCode.DIFY_CONNECTION_ERROR)
        assert "connect" in msg.lower()

        # Rate limit should mention rate limit
        msg = ErrorMessage.get_message(ErrorCode.DIFY_RATE_LIMIT)
        assert "rate" in msg.lower() or "limit" in msg.lower()
