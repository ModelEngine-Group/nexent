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

    def test_datamate_error_codes_exist(self):
        """Test that DataMate error code is defined."""
        assert ErrorCode.DATAMATE_CONNECTION_FAILED is not None

    def test_me_error_codes_exist(self):
        """Test that ME service error code is defined."""
        assert ErrorCode.ME_CONNECTION_FAILED is not None


class TestErrorCodeValues:
    """Test class for ErrorCode string values with leading zeros."""

    def test_dify_auth_error_value(self):
        """Test DIFY_AUTH_ERROR has correct string value."""
        assert ErrorCode.DIFY_AUTH_ERROR.value == "130204"

    def test_dify_config_invalid_value(self):
        """Test DIFY_CONFIG_INVALID has correct string value."""
        assert ErrorCode.DIFY_CONFIG_INVALID.value == "130202"

    def test_dify_connection_error_value(self):
        """Test DIFY_CONNECTION_ERROR has correct string value."""
        assert ErrorCode.DIFY_CONNECTION_ERROR.value == "130203"

    def test_dify_service_error_value(self):
        """Test DIFY_SERVICE_ERROR has correct string value."""
        assert ErrorCode.DIFY_SERVICE_ERROR.value == "130201"

    def test_dify_rate_limit_value(self):
        """Test DIFY_RATE_LIMIT has correct string value."""
        assert ErrorCode.DIFY_RATE_LIMIT.value == "130205"

    def test_dify_response_error_value(self):
        """Test DIFY_RESPONSE_ERROR has correct string value."""
        assert ErrorCode.DIFY_RESPONSE_ERROR.value == "130206"

    def test_datamate_connection_failed_value(self):
        """Test DATAMATE_CONNECTION_FAILED has correct string value."""
        assert ErrorCode.DATAMATE_CONNECTION_FAILED.value == "130101"

    def test_me_connection_failed_value(self):
        """Test ME_CONNECTION_FAILED has correct string value."""
        assert ErrorCode.ME_CONNECTION_FAILED.value == "130301"

    def test_common_validation_error_value(self):
        """Test COMMON_VALIDATION_ERROR has correct string value."""
        assert ErrorCode.COMMON_VALIDATION_ERROR.value == "000101"

    def test_common_unauthorized_value(self):
        """Test COMMON_UNAUTHORIZED has correct string value."""
        assert ErrorCode.COMMON_UNAUTHORIZED.value == "000201"

    def test_common_token_expired_value(self):
        """Test COMMON_TOKEN_EXPIRED has correct string value."""
        assert ErrorCode.COMMON_TOKEN_EXPIRED.value == "000203"

    def test_common_token_invalid_value(self):
        """Test COMMON_TOKEN_INVALID has correct string value."""
        assert ErrorCode.COMMON_TOKEN_INVALID.value == "000204"

    def test_common_rate_limit_exceeded_value(self):
        """Test COMMON_RATE_LIMIT_EXCEEDED has correct string value."""
        assert ErrorCode.COMMON_RATE_LIMIT_EXCEEDED.value == "000302"

    def test_file_not_found_value(self):
        """Test FILE_NOT_FOUND has correct string value."""
        assert ErrorCode.FILE_NOT_FOUND.value == "000401"

    def test_file_too_large_value(self):
        """Test FILE_TOO_LARGE has correct string value."""
        assert ErrorCode.FILE_TOO_LARGE.value == "000403"

    def test_common_resource_not_found_value(self):
        """Test COMMON_RESOURCE_NOT_FOUND has correct string value."""
        assert ErrorCode.COMMON_RESOURCE_NOT_FOUND.value == "000501"

    def test_chat_conversation_not_found_value(self):
        """Test CHAT_CONVERSATION_NOT_FOUND has correct string value."""
        assert ErrorCode.CHAT_CONVERSATION_NOT_FOUND.value == "010101"

    def test_knowledge_not_found_value(self):
        """Test KNOWLEDGE_NOT_FOUND has correct string value."""
        assert ErrorCode.KNOWLEDGE_NOT_FOUND.value == "060101"

    def test_memory_not_found_value(self):
        """Test MEMORY_NOT_FOUND has correct string value."""
        assert ErrorCode.MEMORY_NOT_FOUND.value == "100101"

    def test_model_not_found_value(self):
        """Test MODEL_NOT_FOUND has correct string value."""
        assert ErrorCode.MODEL_NOT_FOUND.value == "090101"

    def test_mcp_connection_failed_value(self):
        """Test MCP_CONNECTION_FAILED has correct string value."""
        assert ErrorCode.MCP_CONNECTION_FAILED.value == "070201"

    def test_northbound_request_failed_value(self):
        """Test NORTHBOUND_REQUEST_FAILED has correct string value."""
        assert ErrorCode.NORTHBOUND_REQUEST_FAILED.value == "140101"

    def test_dataprocess_task_failed_value(self):
        """Test DATAPROCESS_TASK_FAILED has correct string value."""
        assert ErrorCode.DATAPROCESS_TASK_FAILED.value == "150101"

    def test_system_unknown_error_value(self):
        """Test SYSTEM_UNKNOWN_ERROR has correct string value."""
        assert ErrorCode.SYSTEM_UNKNOWN_ERROR.value == "990101"

    def test_system_internal_error_value(self):
        """Test SYSTEM_INTERNAL_ERROR has correct string value."""
        assert ErrorCode.SYSTEM_INTERNAL_ERROR.value == "990105"


class TestErrorCodeHttpStatusMapping:
    """Test class for ERROR_CODE_HTTP_STATUS mapping."""

    def test_dify_auth_error_maps_to_401(self):
        """Test DIFY_AUTH_ERROR maps to HTTP 401."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.DIFY_AUTH_ERROR] == 401

    def test_dify_config_invalid_maps_to_400(self):
        """Test DIFY_CONFIG_INVALID maps to HTTP 400."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.DIFY_CONFIG_INVALID] == 400

    def test_dify_connection_error_maps_to_502(self):
        """Test DIFY_CONNECTION_ERROR maps to HTTP 502."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.DIFY_CONNECTION_ERROR] == 502

    def test_dify_response_error_maps_to_502(self):
        """Test DIFY_RESPONSE_ERROR maps to HTTP 502."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.DIFY_RESPONSE_ERROR] == 502

    def test_dify_rate_limit_maps_to_429(self):
        """Test DIFY_RATE_LIMIT maps to HTTP 429."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.DIFY_RATE_LIMIT] == 429

    def test_common_token_expired_maps_to_401(self):
        """Test COMMON_TOKEN_EXPIRED maps to HTTP 401."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.COMMON_TOKEN_EXPIRED] == 401

    def test_common_token_invalid_maps_to_401(self):
        """Test COMMON_TOKEN_INVALID maps to HTTP 401."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.COMMON_TOKEN_INVALID] == 401

    def test_common_unauthorized_maps_to_401(self):
        """Test COMMON_UNAUTHORIZED maps to HTTP 401."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.COMMON_UNAUTHORIZED] == 401

    def test_common_forbidden_maps_to_403(self):
        """Test COMMON_FORBIDDEN maps to HTTP 403."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.COMMON_FORBIDDEN] == 403

    def test_common_rate_limit_exceeded_maps_to_429(self):
        """Test COMMON_RATE_LIMIT_EXCEEDED maps to HTTP 429."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.COMMON_RATE_LIMIT_EXCEEDED] == 429

    def test_common_validation_error_maps_to_400(self):
        """Test COMMON_VALIDATION_ERROR maps to HTTP 400."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.COMMON_VALIDATION_ERROR] == 400

    def test_common_parameter_invalid_maps_to_400(self):
        """Test COMMON_PARAMETER_INVALID maps to HTTP 400."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.COMMON_PARAMETER_INVALID] == 400

    def test_common_missing_required_field_maps_to_400(self):
        """Test COMMON_MISSING_REQUIRED_FIELD maps to HTTP 400."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.COMMON_MISSING_REQUIRED_FIELD] == 400

    def test_file_too_large_maps_to_413(self):
        """Test FILE_TOO_LARGE maps to HTTP 413."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.FILE_TOO_LARGE] == 413

    def test_file_not_found_maps_to_404(self):
        """Test FILE_NOT_FOUND maps to HTTP 404."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.FILE_NOT_FOUND] == 404

    def test_common_resource_not_found_maps_to_404(self):
        """Test COMMON_RESOURCE_NOT_FOUND maps to HTTP 404."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.COMMON_RESOURCE_NOT_FOUND] == 404

    def test_common_resource_already_exists_maps_to_409(self):
        """Test COMMON_RESOURCE_ALREADY_EXISTS maps to HTTP 409."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.COMMON_RESOURCE_ALREADY_EXISTS] == 409

    def test_common_resource_disabled_maps_to_403(self):
        """Test COMMON_RESOURCE_DISABLED maps to HTTP 403."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.COMMON_RESOURCE_DISABLED] == 403

    def test_system_service_unavailable_maps_to_503(self):
        """Test SYSTEM_SERVICE_UNAVAILABLE maps to HTTP 503."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.SYSTEM_SERVICE_UNAVAILABLE] == 503

    def test_system_timeout_maps_to_504(self):
        """Test SYSTEM_TIMEOUT maps to HTTP 504."""
        assert ERROR_CODE_HTTP_STATUS[ErrorCode.SYSTEM_TIMEOUT] == 504


class TestErrorCodeFormat:
    """Test class for error code format consistency."""

    def test_all_dify_codes_start_with_1302(self):
        """Test all Dify error codes start with 1302 (module 13, sub-module 02)."""
        dify_codes = [
            ErrorCode.DIFY_SERVICE_ERROR,
            ErrorCode.DIFY_CONFIG_INVALID,
            ErrorCode.DIFY_CONNECTION_ERROR,
            ErrorCode.DIFY_AUTH_ERROR,
            ErrorCode.DIFY_RATE_LIMIT,
            ErrorCode.DIFY_RESPONSE_ERROR,
        ]
        for code in dify_codes:
            assert str(code.value).startswith("1302"), f"{code} should start with 1302"

    def test_all_datamate_codes_start_with_1301(self):
        """Test DataMate error code starts with 1301 (module 13, sub-module 01)."""
        assert str(ErrorCode.DATAMATE_CONNECTION_FAILED.value).startswith("1301")

    def test_all_me_codes_start_with_1303(self):
        """Test ME service error code starts with 1303 (module 13, sub-module 03)."""
        assert str(ErrorCode.ME_CONNECTION_FAILED.value).startswith("1303")

    def test_all_common_auth_codes_start_with_0002(self):
        """Test common auth error codes start with 0002."""
        auth_codes = [
            ErrorCode.COMMON_UNAUTHORIZED,
            ErrorCode.COMMON_TOKEN_EXPIRED,
            ErrorCode.COMMON_TOKEN_INVALID,
            ErrorCode.COMMON_FORBIDDEN,
        ]
        for code in auth_codes:
            assert str(code.value).startswith("0002"), f"{code} should start with 0002"

    def test_all_common_validation_codes_start_with_0001(self):
        """Test common validation error codes start with 0001."""
        validation_codes = [
            ErrorCode.COMMON_VALIDATION_ERROR,
            ErrorCode.COMMON_PARAMETER_INVALID,
            ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
        ]
        for code in validation_codes:
            assert str(code.value).startswith("0001"), f"{code} should start with 0001"

    def test_all_system_codes_start_with_99(self):
        """Test system error codes start with 99."""
        system_codes = [
            ErrorCode.SYSTEM_UNKNOWN_ERROR,
            ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
            ErrorCode.SYSTEM_DATABASE_ERROR,
            ErrorCode.SYSTEM_TIMEOUT,
            ErrorCode.SYSTEM_INTERNAL_ERROR,
        ]
        for code in system_codes:
            assert str(code.value).startswith("99"), f"{code} should start with 99"

    def test_all_chat_codes_start_with_01(self):
        """Test chat error codes start with 01."""
        assert str(ErrorCode.CHAT_CONVERSATION_NOT_FOUND.value).startswith("01")

    def test_all_knowledge_codes_start_with_06(self):
        """Test knowledge error codes start with 06."""
        assert str(ErrorCode.KNOWLEDGE_NOT_FOUND.value).startswith("06")

    def test_all_mcp_codes_start_with_07(self):
        """Test MCP error codes start with 07."""
        assert str(ErrorCode.MCP_CONNECTION_FAILED.value).startswith("07")

    def test_all_model_codes_start_with_09(self):
        """Test model error codes start with 09."""
        assert str(ErrorCode.MODEL_NOT_FOUND.value).startswith("09")

    def test_all_memory_codes_start_with_10(self):
        """Test memory error codes start with 10."""
        assert str(ErrorCode.MEMORY_NOT_FOUND.value).startswith("10")

    def test_all_northbound_codes_start_with_14(self):
        """Test northbound error codes start with 14."""
        assert str(ErrorCode.NORTHBOUND_REQUEST_FAILED.value).startswith("14")

    def test_all_dataprocess_codes_start_with_15(self):
        """Test dataprocess error codes start with 15."""
        assert str(ErrorCode.DATAPROCESS_TASK_FAILED.value).startswith("15")


class TestErrorCodeStringFormat:
    """Test that ErrorCode values are strings with 6 digits."""

    def test_error_code_is_string(self):
        """Test ErrorCode values are strings."""
        assert isinstance(ErrorCode.DIFY_AUTH_ERROR.value, str)
        assert ErrorCode.DIFY_AUTH_ERROR.value == "130204"

    def test_error_code_preserves_leading_zeros(self):
        """Test ErrorCode values preserve leading zeros."""
        # Common codes have leading zeros
        assert ErrorCode.COMMON_VALIDATION_ERROR.value == "000101"
        assert ErrorCode.COMMON_UNAUTHORIZED.value == "000201"
        assert ErrorCode.COMMON_RATE_LIMIT_EXCEEDED.value == "000302"

    def test_error_code_length_is_six(self):
        """Test all ErrorCode values have 6 digits."""
        all_codes = [
            ErrorCode.COMMON_VALIDATION_ERROR,
            ErrorCode.COMMON_UNAUTHORIZED,
            ErrorCode.COMMON_TOKEN_EXPIRED,
            ErrorCode.DIFY_AUTH_ERROR,
            ErrorCode.DATAMATE_CONNECTION_FAILED,
            ErrorCode.CHAT_CONVERSATION_NOT_FOUND,
            ErrorCode.KNOWLEDGE_NOT_FOUND,
            ErrorCode.MCP_CONNECTION_FAILED,
            ErrorCode.SYSTEM_UNKNOWN_ERROR,
        ]
        for code in all_codes:
            assert len(code.value) == 6, f"{code} should have 6 digits"


class TestErrorCodeIntConversion:
    """Test ErrorCode can be converted to integer for JSON response."""

    def test_error_code_can_be_converted_to_int(self):
        """Test ErrorCode value can be converted to int for HTTP response."""
        # The response should use int() to convert string to number
        assert int(ErrorCode.DIFY_AUTH_ERROR.value) == 130204
        assert int(ErrorCode.COMMON_VALIDATION_ERROR.value) == 101

    def test_error_code_in_conditional(self):
        """Test ErrorCode can be used in conditionals."""
        code = ErrorCode.DIFY_AUTH_ERROR
        if code.value == "130204":
            assert True
        else:
            assert False
