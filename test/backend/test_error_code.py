"""
Unit tests for Error Code definitions.

Tests the ErrorCode enum and ERROR_CODE_HTTP_STATUS mapping
to ensure error codes are properly defined and mapped.
"""
import pytest
from backend.consts.error_code import ErrorCode, ERROR_CODE_HTTP_STATUS


class TestErrorCodeEnum:
    """Test class for ErrorCode enum values."""

    def test_dify_error_codes_exist(self):
        """Test that all Dify-related error codes are defined."""
        assert ErrorCode.DIFY_SERVICE_ERROR is not None
        assert ErrorCode.DIFY_CONFIG_INVALID is not None
        assert ErrorCode.DIFY_CONNECTION_ERROR is not None
        assert ErrorCode.DIFY_AUTH_ERROR is not None
        assert ErrorCode.DIFY_RATE_LIMIT is not None
        assert ErrorCode.DIFY_RESPONSE_ERROR is not None

    def test_dify_auth_error_value(self):
        """Test DIFY_AUTH_ERROR has correct value."""
        assert ErrorCode.DIFY_AUTH_ERROR.value == 116103

    def test_dify_config_invalid_value(self):
        """Test DIFY_CONFIG_INVALID has correct value."""
        assert ErrorCode.DIFY_CONFIG_INVALID.value == 116101

    def test_dify_connection_error_value(self):
        """Test DIFY_CONNECTION_ERROR has correct value."""
        assert ErrorCode.DIFY_CONNECTION_ERROR.value == 116102

    def test_dify_service_error_value(self):
        """Test DIFY_SERVICE_ERROR has correct value."""
        assert ErrorCode.DIFY_SERVICE_ERROR.value == 116003

    def test_dify_rate_limit_value(self):
        """Test DIFY_RATE_LIMIT has correct value."""
        assert ErrorCode.DIFY_RATE_LIMIT.value == 116104

    def test_dify_response_error_value(self):
        """Test DIFY_RESPONSE_ERROR has correct value."""
        assert ErrorCode.DIFY_RESPONSE_ERROR.value == 116105


class TestErrorCodeHttpStatusMapping:
    """Test class for ERROR_CODE_HTTP_STATUS mapping."""

    def test_dify_auth_error_maps_to_401(self):
        """Test DIFY_AUTH_ERROR maps to HTTP 401."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.DIFY_AUTH_ERROR] == 401

    def test_dify_config_invalid_maps_to_401(self):
        """Test DIFY_CONFIG_INVALID maps to HTTP 401."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.DIFY_CONFIG_INVALID] == 401

    def test_dify_connection_error_maps_to_502(self):
        """Test DIFY_CONNECTION_ERROR maps to HTTP 502."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.DIFY_CONNECTION_ERROR] == 502

    def test_dify_response_error_maps_to_502(self):
        """Test DIFY_RESPONSE_ERROR maps to HTTP 502."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.DIFY_RESPONSE_ERROR] == 502

    def test_dify_rate_limit_maps_to_429(self):
        """Test DIFY_RATE_LIMIT maps to HTTP 429."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.DIFY_RATE_LIMIT] == 429

    def test_token_expired_maps_to_401(self):
        """Test TOKEN_EXPIRED maps to HTTP 401."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.TOKEN_EXPIRED] == 401

    def test_token_invalid_maps_to_401(self):
        """Test TOKEN_INVALID maps to HTTP 401."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.TOKEN_INVALID] == 401

    def test_unauthorized_maps_to_401(self):
        """Test UNAUTHORIZED maps to HTTP 401."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.UNAUTHORIZED] == 401

    def test_forbidden_maps_to_403(self):
        """Test FORBIDDEN maps to HTTP 403."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.FORBIDDEN] == 403

    def test_rate_limit_exceeded_maps_to_429(self):
        """Test RATE_LIMIT_EXCEEDED maps to HTTP 429."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.RATE_LIMIT_EXCEEDED] == 429

    def test_validation_error_maps_to_400(self):
        """Test VALIDATION_ERROR maps to HTTP 400."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.VALIDATION_ERROR] == 400

    def test_parameter_invalid_maps_to_400(self):
        """Test PARAMETER_INVALID maps to HTTP 400."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.PARAMETER_INVALID] == 400

    def test_missing_required_field_maps_to_400(self):
        """Test MISSING_REQUIRED_FIELD maps to HTTP 400."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.MISSING_REQUIRED_FIELD] == 400

    def test_file_too_large_maps_to_413(self):
        """Test FILE_TOO_LARGE maps to HTTP 413."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.FILE_TOO_LARGE] == 413


class TestErrorCodeFormat:
    """Test class for error code format consistency."""

    def test_all_dify_codes_start_with_116(self):
        """Test all Dify error codes start with 116."""
        dify_codes = [
            ErrorCode.DIFY_SERVICE_ERROR,
            ErrorCode.DIFY_CONFIG_INVALID,
            ErrorCode.DIFY_CONNECTION_ERROR,
            ErrorCode.DIFY_AUTH_ERROR,
            ErrorCode.DIFY_RATE_LIMIT,
            ErrorCode.DIFY_RESPONSE_ERROR,
        ]
        for code in dify_codes:
            assert str(code.value).startswith("116"), f"{code} should start with 116"

    def test_auth_codes_start_with_102(self):
        """Test auth error codes start with 102."""
        auth_codes = [
            ErrorCode.UNAUTHORIZED,
            ErrorCode.TOKEN_EXPIRED,
            ErrorCode.TOKEN_INVALID,
            ErrorCode.SIGNATURE_INVALID,
            ErrorCode.FORBIDDEN,
        ]
        for code in auth_codes:
            assert str(code.value).startswith("102"), f"{code} should start with 102"

    def test_system_codes_start_with_101(self):
        """Test system error codes start with 101."""
        system_codes = [
            ErrorCode.UNKNOWN_ERROR,
            ErrorCode.SERVICE_UNAVAILABLE,
            ErrorCode.DATABASE_ERROR,
            ErrorCode.TIMEOUT,
            ErrorCode.INTERNAL_ERROR,
        ]
        for code in system_codes:
            assert str(code.value).startswith("101"), f"{code} should start with 101"


class TestErrorCodeIntEnum:
    """Test that ErrorCode properly inherits from int and Enum."""

    def test_error_code_is_int(self):
        """Test ErrorCode values can be used as integers."""
        assert isinstance(ErrorCode.DIFY_AUTH_ERROR.value, int)
        assert ErrorCode.DIFY_AUTH_ERROR.value + 1 == 116104

    def test_error_code_comparison(self):
        """Test ErrorCode can be compared with integers."""
        assert ErrorCode.DIFY_AUTH_ERROR == 116103
        assert ErrorCode.DIFY_AUTH_ERROR.value == 116103

    def test_error_code_in_conditional(self):
        """Test ErrorCode can be used in conditionals."""
        code = ErrorCode.DIFY_AUTH_ERROR
        if code == 116103:
            assert True
        else:
            assert False
