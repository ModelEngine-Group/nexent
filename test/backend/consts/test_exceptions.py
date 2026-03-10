"""
Unit tests for Exception classes.

Tests the AppException class and helper functions.
"""
import pytest
from backend.consts.error_code import ErrorCode
from backend.consts.exceptions import AppException, raise_error


class TestAppException:
    """Test class for AppException."""

    def test_app_exception_creation_with_code(self):
        """Test creating AppException with error code."""
        exc = AppException(ErrorCode.DIFY_AUTH_ERROR)
        assert exc.error_code == ErrorCode.DIFY_AUTH_ERROR

    def test_app_exception_creation_with_custom_message(self):
        """Test creating AppException with custom message."""
        custom_msg = "Custom error message"
        exc = AppException(ErrorCode.DIFY_AUTH_ERROR, custom_msg)
        assert exc.message == custom_msg

    def test_app_exception_default_message(self):
        """Test that AppException uses default message when not provided."""
        exc = AppException(ErrorCode.DIFY_AUTH_ERROR)
        # Default message should be from ErrorMessage
        assert exc.message != ""
        assert "Dify authentication failed" in exc.message

    def test_app_exception_with_details(self):
        """Test creating AppException with details."""
        details = {"field": "api_key", "reason": "invalid"}
        exc = AppException(ErrorCode.DIFY_CONFIG_INVALID, "Invalid config", details)
        assert exc.details == details

    def test_app_exception_empty_details_defaults_to_dict(self):
        """Test that empty details defaults to empty dict."""
        exc = AppException(ErrorCode.DIFY_AUTH_ERROR)
        assert exc.details == {}

    def test_app_exception_to_dict(self):
        """Test AppException.to_dict() method."""
        exc = AppException(ErrorCode.DIFY_AUTH_ERROR, "Auth failed", {"key": "value"})
        result = exc.to_dict()

        assert result["code"] == "130204"
        assert result["message"] == "Auth failed"
        assert result["details"] == {"key": "value"}

    def test_app_exception_to_dict_null_details(self):
        """Test that to_dict() returns null for empty details."""
        exc = AppException(ErrorCode.DIFY_AUTH_ERROR, "Auth failed")
        result = exc.to_dict()

        assert result["details"] is None

    def test_app_exception_http_status_property(self):
        """Test AppException.http_status property."""
        exc = AppException(ErrorCode.DIFY_AUTH_ERROR)
        assert exc.http_status == 401

    def test_app_exception_http_status_for_different_codes(self):
        """Test http_status for different error codes."""
        test_cases = [
            (ErrorCode.DIFY_AUTH_ERROR, 401),
            (ErrorCode.DIFY_CONFIG_INVALID, 400),
            (ErrorCode.DIFY_RATE_LIMIT, 429),
            (ErrorCode.COMMON_VALIDATION_ERROR, 400),
            (ErrorCode.COMMON_TOKEN_EXPIRED, 401),
            (ErrorCode.COMMON_FORBIDDEN, 403),
        ]

        for error_code, expected_status in test_cases:
            exc = AppException(error_code)
            assert exc.http_status == expected_status, \
                f"Expected {expected_status} for {error_code}"

    def test_app_exception_is_subclass_of_exception(self):
        """Test that AppException is a subclass of Exception."""
        assert issubclass(AppException, Exception)

    def test_app_exception_can_be_raised_and_caught(self):
        """Test that AppException can be raised and caught."""
        try:
            raise AppException(ErrorCode.DIFY_AUTH_ERROR, "Test error")
        except AppException as e:
            assert e.error_code == ErrorCode.DIFY_AUTH_ERROR
            assert e.message == "Test error"

    def test_app_exception_str_representation(self):
        """Test string representation of AppException."""
        exc = AppException(ErrorCode.DIFY_AUTH_ERROR, "Test error")
        assert str(exc) == "Test error"


class TestRaiseError:
    """Test class for raise_error helper function."""

    def test_raise_error_raises_app_exception(self):
        """Test that raise_error raises AppException."""
        with pytest.raises(AppException):
            raise_error(ErrorCode.DIFY_AUTH_ERROR)

    def test_raise_error_with_custom_message(self):
        """Test raise_error with custom message."""
        custom_msg = "Custom error"
        try:
            raise_error(ErrorCode.DIFY_AUTH_ERROR, custom_msg)
        except AppException as e:
            assert e.message == custom_msg

    def test_raise_error_with_details(self):
        """Test raise_error with details."""
        details = {"info": "test"}
        try:
            raise_error(ErrorCode.DIFY_CONFIG_INVALID, "Error", details)
        except AppException as e:
            assert e.details == details


class TestLegacyExceptions:
    """Test class for legacy exception classes."""

    def test_agent_run_exception_exists(self):
        """Test AgentRunException can be instantiated."""
        from backend.consts.exceptions import AgentRunException
        exc = AgentRunException("Agent run failed")
        assert str(exc) == "Agent run failed"

    def test_limit_exceeded_error_exists(self):
        """Test LimitExceededError can be instantiated."""
        from backend.consts.exceptions import LimitExceededError
        exc = LimitExceededError("Rate limit exceeded")
        assert str(exc) == "Rate limit exceeded"

    def test_unauthorized_error_exists(self):
        """Test UnauthorizedError can be instantiated."""
        from backend.consts.exceptions import UnauthorizedError
        exc = UnauthorizedError("Unauthorized")
        assert str(exc) == "Unauthorized"

    def test_validation_error_exists(self):
        """Test ValidationError can be instantiated."""
        from backend.consts.exceptions import ValidationError
        exc = ValidationError("Validation failed")
        assert str(exc) == "Validation failed"

    def test_not_found_exception_exists(self):
        """Test NotFoundException can be instantiated."""
        from backend.consts.exceptions import NotFoundException
        exc = NotFoundException("Resource not found")
        assert str(exc) == "Resource not found"

    def test_mcp_connection_error_exists(self):
        """Test MCPConnectionError can be instantiated."""
        from backend.consts.exceptions import MCPConnectionError
        exc = MCPConnectionError("MCP connection failed")
        assert str(exc) == "MCP connection failed"

    def test_data_mate_connection_error_exists(self):
        """Test DataMateConnectionError can be instantiated."""
        from backend.consts.exceptions import DataMateConnectionError
        exc = DataMateConnectionError("DataMate connection failed")
        assert str(exc) == "DataMate connection failed"


class TestLegacyAliases:
    """Test class for legacy exception aliases."""

    def test_parameter_invalid_error_alias(self):
        """Test ParameterInvalidError alias exists."""
        from backend.consts.exceptions import ParameterInvalidError
        assert ParameterInvalidError is not None

    def test_timeout_error_alias(self):
        """Test TimeoutError alias exists."""
        from backend.consts.exceptions import TimeoutError
        assert TimeoutError is not None

    def test_user_not_found_error_alias(self):
        """Test UserNotFoundError alias exists."""
        from backend.consts.exceptions import UserNotFoundError
        assert UserNotFoundError is not None

    def test_tenant_not_found_error_alias(self):
        """Test TenantNotFoundError alias exists."""
        from backend.consts.exceptions import TenantNotFoundError
        assert TenantNotFoundError is not None

    def test_agent_not_found_error_alias(self):
        """Test AgentNotFoundError alias exists."""
        from backend.consts.exceptions import AgentNotFoundError
        assert AgentNotFoundError is not None
