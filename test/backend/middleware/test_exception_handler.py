"""
Unit tests for Exception Handler Middleware.

Tests the ExceptionHandlerMiddleware class and helper functions
for centralized error handling in the FastAPI application.
"""
import atexit
import sys
import os

# Add backend directory to path for imports BEFORE any module imports
# From test/backend/middleware/ -> go up 3 levels to project root -> backend/
backend_dir = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "../../../backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import pytest
from fastapi import Request, HTTPException
from fastapi.responses import Response
from backend.middleware.exception_handler import (
    ExceptionHandlerMiddleware,
    _http_status_to_error_code,
    create_error_response,
    create_success_response,
)
from consts.exceptions import AppException
from consts.error_code import ErrorCode
from unittest.mock import patch, MagicMock, AsyncMock, Mock


# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()

# Start critical patches first - storage factory and config validation must be patched
# before any module imports that might trigger MinioClient initialization
critical_patches = [
    # Patch storage factory and MinIO config validation FIRST
    patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
          return_value=storage_client_mock),
    patch('nexent.storage.minio_config.MinIOStorageConfig.validate',
          lambda self: None),
    # Mock boto3 client
    patch('boto3.client', return_value=Mock()),
    # Mock boto3 resource
    patch('boto3.resource', return_value=Mock()),
    # Mock Elasticsearch to prevent connection errors
    patch('elasticsearch.Elasticsearch', return_value=Mock()),
]

for p in critical_patches:
    p.start()

# Patch MinioClient class to return mock instance when instantiated
# This prevents real initialization during module import
patches = [
    patch('backend.database.client.MinioClient', return_value=minio_mock),
    patch('database.client.MinioClient', return_value=minio_mock),
    patch('backend.database.client.minio_client', minio_mock),
]

for p in patches:
    p.start()

# Combine all patches for cleanup
all_patches = critical_patches + patches

# Now safe to import modules that use database.client
# After import, we can patch get_db_session if needed
try:
    from backend.database import client as db_client_module
    # Patch get_db_session after module is imported
    db_session_patch = patch.object(
        db_client_module, 'get_db_session', return_value=Mock())
    db_session_patch.start()
    all_patches.append(db_session_patch)
except ImportError:
    # If import fails, try patching the path directly (may trigger import)
    db_session_patch = patch(
        'backend.database.client.get_db_session', return_value=Mock())
    db_session_patch.start()
    all_patches.append(db_session_patch)

# Now safe to import app modules - AFTER all patches are applied
# Import exception classes

# Import pytest for test decorators

# Stop all patches at the end of the module


def stop_patches():
    for p in all_patches:
        p.stop()


atexit.register(stop_patches)


class TestHttpStatusToErrorCode:
    """Test class for _http_status_to_error_code function."""

    def test_maps_400_to_common_validation_error(self):
        """Test that HTTP 400 maps to COMMON_VALIDATION_ERROR."""
        assert _http_status_to_error_code(400) == ErrorCode.COMMON_VALIDATION_ERROR

    def test_maps_401_to_common_unauthorized(self):
        """Test that HTTP 401 maps to COMMON_UNAUTHORIZED."""
        assert _http_status_to_error_code(401) == ErrorCode.COMMON_UNAUTHORIZED

    def test_maps_403_to_common_forbidden(self):
        """Test that HTTP 403 maps to COMMON_FORBIDDEN."""
        assert _http_status_to_error_code(403) == ErrorCode.COMMON_FORBIDDEN

    def test_maps_404_to_common_resource_not_found(self):
        """Test that HTTP 404 maps to COMMON_RESOURCE_NOT_FOUND."""
        assert _http_status_to_error_code(404) == ErrorCode.COMMON_RESOURCE_NOT_FOUND

    def test_maps_429_to_common_rate_limit_exceeded(self):
        """Test that HTTP 429 maps to COMMON_RATE_LIMIT_EXCEEDED."""
        assert _http_status_to_error_code(429) == ErrorCode.COMMON_RATE_LIMIT_EXCEEDED

    def test_maps_500_to_system_internal_error(self):
        """Test that HTTP 500 maps to SYSTEM_INTERNAL_ERROR."""
        assert _http_status_to_error_code(500) == ErrorCode.SYSTEM_INTERNAL_ERROR

    def test_maps_502_to_system_service_unavailable(self):
        """Test that HTTP 502 maps to SYSTEM_SERVICE_UNAVAILABLE."""
        assert _http_status_to_error_code(502) == ErrorCode.SYSTEM_SERVICE_UNAVAILABLE

    def test_maps_503_to_system_service_unavailable(self):
        """Test that HTTP 503 maps to SYSTEM_SERVICE_UNAVAILABLE."""
        assert _http_status_to_error_code(503) == ErrorCode.SYSTEM_SERVICE_UNAVAILABLE

    def test_unknown_status_returns_system_unknown_error(self):
        """Test that unknown HTTP status codes map to SYSTEM_UNKNOWN_ERROR."""
        assert _http_status_to_error_code(418) == ErrorCode.SYSTEM_UNKNOWN_ERROR
        assert _http_status_to_error_code(599) == ErrorCode.SYSTEM_UNKNOWN_ERROR


class TestCreateErrorResponse:
    """Test class for create_error_response function."""

    def test_create_error_response_default(self):
        """Test creating error response with default values."""
        response = create_error_response(ErrorCode.DIFY_AUTH_ERROR)

        assert response.status_code == 401
        assert response.body is not None

    def test_create_error_response_custom_message(self):
        """Test creating error response with custom message."""
        custom_message = "Custom error message"
        response = create_error_response(
            ErrorCode.DIFY_AUTH_ERROR,
            message=custom_message
        )

        assert response.status_code == 401

    def test_create_error_response_with_trace_id(self):
        """Test creating error response with trace ID."""
        trace_id = "test-trace-id-123"
        response = create_error_response(
            ErrorCode.DIFY_AUTH_ERROR,
            trace_id=trace_id
        )

        assert response.status_code == 401

    def test_create_error_response_with_details(self):
        """Test creating error response with additional details."""
        details = {"field": "api_key", "issue": "invalid format"}
        response = create_error_response(
            ErrorCode.DIFY_CONFIG_INVALID,
            details=details
        )

        assert response.status_code == 400

    def test_create_error_response_custom_http_status(self):
        """Test creating error response with custom HTTP status."""
        response = create_error_response(
            ErrorCode.DIFY_SERVICE_ERROR,
            http_status=502
        )

        assert response.status_code == 502

    def test_create_error_response_dify_auth_error(self):
        """Test creating error response for DIFY_AUTH_ERROR."""
        response = create_error_response(ErrorCode.DIFY_AUTH_ERROR)

        assert response.status_code == 401

    def test_create_error_response_dify_config_invalid(self):
        """Test creating error response for DIFY_CONFIG_INVALID."""
        response = create_error_response(ErrorCode.DIFY_CONFIG_INVALID)

        assert response.status_code == 400

    def test_create_error_response_dify_rate_limit(self):
        """Test creating error response for DIFY_RATE_LIMIT."""
        response = create_error_response(ErrorCode.DIFY_RATE_LIMIT)

        assert response.status_code == 429

    def test_create_error_response_validation_error(self):
        """Test creating error response for COMMON_VALIDATION_ERROR."""
        response = create_error_response(ErrorCode.COMMON_VALIDATION_ERROR)

        assert response.status_code == 400

    def test_create_error_response_token_expired(self):
        """Test creating error response for COMMON_TOKEN_EXPIRED."""
        response = create_error_response(ErrorCode.COMMON_TOKEN_EXPIRED)

        assert response.status_code == 401


class TestCreateSuccessResponse:
    """Test class for create_success_response function."""

    def test_create_success_response_default(self):
        """Test creating success response with default values."""
        response = create_success_response()

        assert response.status_code == 200

    def test_create_success_response_with_data(self):
        """Test creating success response with data."""
        data = {"key": "value"}
        response = create_success_response(data=data)

        assert response.status_code == 200

    def test_create_success_response_custom_message(self):
        """Test creating success response with custom message."""
        response = create_success_response(message="Operation successful")

        assert response.status_code == 200

    def test_create_success_response_with_trace_id(self):
        """Test creating success response with trace ID."""
        trace_id = "test-trace-id-456"
        response = create_success_response(trace_id=trace_id)

        assert response.status_code == 200

    def test_create_success_response_all_params(self):
        """Test creating success response with all parameters."""
        data = {"result": "ok"}
        message = "Success"
        trace_id = "trace-789"
        response = create_success_response(
            data=data,
            message=message,
            trace_id=trace_id
        )

        assert response.status_code == 200


class TestExceptionHandlerMiddleware:
    """Test class for ExceptionHandlerMiddleware."""

    @pytest.mark.asyncio
    async def test_dispatch_normal_request(self):
        """Test that normal requests pass through without error."""
        middleware = ExceptionHandlerMiddleware(app=MagicMock())

        mock_request = MagicMock(spec=Request)
        mock_request.state = MagicMock()

        mock_response = MagicMock(spec=Response)
        mock_call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once_with(mock_request)
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_dispatch_app_exception(self):
        """Test handling of AppException."""
        middleware = ExceptionHandlerMiddleware(app=MagicMock())

        mock_request = MagicMock(spec=Request)
        mock_request.state = MagicMock()

        # Simulate AppException being raised
        app_exception = AppException(
            ErrorCode.DIFY_AUTH_ERROR,
            "Dify authentication failed"
        )
        mock_call_next = AsyncMock(side_effect=app_exception)

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_dispatch_http_exception(self):
        """Test handling of FastAPI HTTPException."""
        middleware = ExceptionHandlerMiddleware(app=MagicMock())

        mock_request = MagicMock(spec=Request)
        mock_request.state = MagicMock()

        # Simulate HTTPException being raised
        http_exception = HTTPException(status_code=404, detail="Not found")
        mock_call_next = AsyncMock(side_effect=http_exception)

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_dispatch_generic_exception(self):
        """Test handling of generic exceptions."""
        middleware = ExceptionHandlerMiddleware(app=MagicMock())

        mock_request = MagicMock(spec=Request)
        mock_request.state = MagicMock()

        # Simulate generic exception being raised
        generic_exception = RuntimeError("Something went wrong")
        mock_call_next = AsyncMock(side_effect=generic_exception)

        response = await middleware.dispatch(mock_request, mock_call_next)

        # Should return 500 with internal error code
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_trace_id_generated(self):
        """Test that trace ID is generated for each request."""
        middleware = ExceptionHandlerMiddleware(app=MagicMock())

        mock_request = MagicMock(spec=Request)
        mock_request.state = MagicMock()

        mock_response = MagicMock(spec=Response)
        mock_call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, mock_call_next)

        # Verify trace_id was set on request.state
        assert hasattr(mock_request.state, 'trace_id')

    @pytest.mark.asyncio
    async def test_app_exception_with_details(self):
        """Test handling of AppException with details."""
        middleware = ExceptionHandlerMiddleware(app=MagicMock())

        mock_request = MagicMock(spec=Request)
        mock_request.state = MagicMock()

        # AppException with details
        app_exception = AppException(
            ErrorCode.DIFY_CONFIG_INVALID,
            "Invalid configuration",
            details={"field": "api_key"}
        )
        mock_call_next = AsyncMock(side_effect=app_exception)

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_different_error_codes_map_to_correct_status(self):
        """Test that different error codes produce correct HTTP status."""
        test_cases = [
            (ErrorCode.COMMON_TOKEN_EXPIRED, 401),
            (ErrorCode.COMMON_TOKEN_INVALID, 401),
            (ErrorCode.COMMON_FORBIDDEN, 403),
            (ErrorCode.COMMON_RATE_LIMIT_EXCEEDED, 429),
            (ErrorCode.COMMON_VALIDATION_ERROR, 400),
            (ErrorCode.FILE_TOO_LARGE, 413),
        ]

        middleware = ExceptionHandlerMiddleware(app=MagicMock())
        mock_request = MagicMock(spec=Request)
        mock_request.state = MagicMock()

        for error_code, expected_status in test_cases:
            app_exception = AppException(error_code, "Test error")
            mock_call_next = AsyncMock(side_effect=app_exception)

            response = await middleware.dispatch(mock_request, mock_call_next)

            assert response.status_code == expected_status, \
                f"Expected {expected_status} for {error_code}, got {response.status_code}"


class TestErrorResponseFormat:
    """Test class for error response format."""

    def test_error_response_contains_code_as_int(self):
        """Test that error response contains code as integer."""
        response = create_error_response(ErrorCode.DIFY_AUTH_ERROR)
        # Parse response body
        import json
        body = json.loads(response.body)
        assert "code" in body
        # Code should be integer when converted (string "130204" -> int 130204)
        assert body["code"] == 130204

    def test_error_response_contains_message(self):
        """Test that error response contains message."""
        response = create_error_response(ErrorCode.DIFY_AUTH_ERROR, message="Custom message")
        import json
        body = json.loads(response.body)
        assert body["message"] == "Custom message"

    def test_error_response_contains_trace_id(self):
        """Test that error response contains trace_id."""
        response = create_error_response(ErrorCode.DIFY_AUTH_ERROR, trace_id="test-123")
        import json
        body = json.loads(response.body)
        assert body["trace_id"] == "test-123"

    def test_error_response_contains_details(self):
        """Test that error response contains details."""
        details = {"field": "api_key", "reason": "invalid"}
        response = create_error_response(ErrorCode.DIFY_CONFIG_INVALID, details=details)
        import json
        body = json.loads(response.body)
        assert body["details"] == details

    def test_error_response_details_null_when_not_provided(self):
        """Test that details is null when not provided."""
        response = create_error_response(ErrorCode.DIFY_AUTH_ERROR)
        import json
        body = json.loads(response.body)
        assert body["details"] is None


class TestNewErrorCodes:
    """Test class for new error codes."""

    def test_datamate_connection_failed(self):
        """Test DATAMATE_CONNECTION_FAILED error code."""
        assert ErrorCode.DATAMATE_CONNECTION_FAILED.value == "130101"

    def test_me_connection_failed(self):
        """Test ME_CONNECTION_FAILED error code."""
        assert ErrorCode.ME_CONNECTION_FAILED.value == "130301"

    def test_northbound_request_failed(self):
        """Test NORTHBOUND_REQUEST_FAILED error code."""
        assert ErrorCode.NORTHBOUND_REQUEST_FAILED.value == "140101"

    def test_northbound_config_invalid(self):
        """Test NORTHBOUND_CONFIG_INVALID error code."""
        assert ErrorCode.NORTHBOUND_CONFIG_INVALID.value == "140201"

    def test_dataprocess_task_failed(self):
        """Test DATAPROCESS_TASK_FAILED error code."""
        assert ErrorCode.DATAPROCESS_TASK_FAILED.value == "150101"

    def test_dataprocess_parse_failed(self):
        """Test DATAPROCESS_PARSE_FAILED error code."""
        assert ErrorCode.DATAPROCESS_PARSE_FAILED.value == "150102"

    def test_quick_config_invalid(self):
        """Test QUICK_CONFIG_INVALID error code."""
        assert ErrorCode.QUICK_CONFIG_INVALID.value == "020101"

    def test_agentspace_agent_not_found(self):
        """Test AGENTSPACE_AGENT_NOT_FOUND error code."""
        assert ErrorCode.AGENTSPACE_AGENT_NOT_FOUND.value == "030101"

    def test_knowledge_not_found(self):
        """Test KNOWLEDGE_NOT_FOUND error code."""
        assert ErrorCode.KNOWLEDGE_NOT_FOUND.value == "060101"

    def test_memory_not_found(self):
        """Test MEMORY_NOT_FOUND error code."""
        assert ErrorCode.MEMORY_NOT_FOUND.value == "100101"

    def test_profile_user_not_found(self):
        """Test PROFILE_USER_NOT_FOUND error code."""
        assert ErrorCode.PROFILE_USER_NOT_FOUND.value == "110101"

    def test_tenant_not_found(self):
        """Test TENANT_NOT_FOUND error code."""
        assert ErrorCode.TENANT_NOT_FOUND.value == "120101"

    def test_mcp_tool_not_found(self):
        """Test MCP_TOOL_NOT_FOUND error code."""
        assert ErrorCode.MCP_TOOL_NOT_FOUND.value == "070101"

    def test_mcp_name_illegal(self):
        """Test MCP_NAME_ILLEGAL error code."""
        assert ErrorCode.MCP_NAME_ILLEGAL.value == "070301"

    def test_model_not_found(self):
        """Test MODEL_NOT_FOUND error code."""
        assert ErrorCode.MODEL_NOT_FOUND.value == "090101"


class TestAppExceptionToDict:
    """Test class for AppException.to_dict() method."""

    def test_to_dict_contains_code(self):
        """Test that to_dict contains code as integer."""
        exc = AppException(ErrorCode.DIFY_AUTH_ERROR, "Auth failed")
        result = exc.to_dict()
        assert result["code"] == 130204

    def test_to_dict_contains_message(self):
        """Test that to_dict contains message."""
        exc = AppException(ErrorCode.DIFY_AUTH_ERROR, "Custom message")
        result = exc.to_dict()
        assert result["message"] == "Custom message"

    def test_to_dict_contains_details(self):
        """Test that to_dict contains details."""
        exc = AppException(ErrorCode.DIFY_CONFIG_INVALID, "Invalid", details={"key": "value"})
        result = exc.to_dict()
        assert result["details"] == {"key": "value"}

    def test_to_dict_details_null_when_empty(self):
        """Test that details is null when empty dict."""
        exc = AppException(ErrorCode.DIFY_AUTH_ERROR, "Auth failed", details={})
        result = exc.to_dict()
        assert result["details"] is None
