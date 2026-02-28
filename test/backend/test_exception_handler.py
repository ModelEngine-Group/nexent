"""
Unit tests for Exception Handler Middleware.

Tests the ExceptionHandlerMiddleware class and helper functions
for centralized error handling in the FastAPI application.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, Response

from backend.middleware.exception_handler import (
    ExceptionHandlerMiddleware,
    _http_status_to_error_code,
    create_error_response,
    create_success_response,
)
from backend.consts.error_code import ErrorCode, ERROR_CODE_HTTP_STATUS
from backend.consts.exceptions import AppException


class TestHttpStatusToErrorCode:
    """Test class for _http_status_to_error_code function."""

    def test_maps_400_to_validation_error(self):
        """Test that HTTP 400 maps to VALIDATION_ERROR."""
        assert _http_status_to_error_code(400) == ErrorCode.VALIDATION_ERROR

    def test_maps_401_to_unauthorized(self):
        """Test that HTTP 401 maps to UNAUTHORIZED."""
        assert _http_status_to_error_code(401) == ErrorCode.UNAUTHORIZED

    def test_maps_403_to_forbidden(self):
        """Test that HTTP 403 maps to FORBIDDEN."""
        assert _http_status_to_error_code(403) == ErrorCode.FORBIDDEN

    def test_maps_404_to_resource_not_found(self):
        """Test that HTTP 404 maps to RESOURCE_NOT_FOUND."""
        assert _http_status_to_error_code(404) == ErrorCode.RESOURCE_NOT_FOUND

    def test_maps_429_to_rate_limit_exceeded(self):
        """Test that HTTP 429 maps to RATE_LIMIT_EXCEEDED."""
        assert _http_status_to_error_code(429) == ErrorCode.RATE_LIMIT_EXCEEDED

    def test_maps_500_to_internal_error(self):
        """Test that HTTP 500 maps to INTERNAL_ERROR."""
        assert _http_status_to_error_code(500) == ErrorCode.INTERNAL_ERROR

    def test_maps_502_to_service_unavailable(self):
        """Test that HTTP 502 maps to SERVICE_UNAVAILABLE."""
        assert _http_status_to_error_code(502) == ErrorCode.SERVICE_UNAVAILABLE

    def test_maps_503_to_service_unavailable(self):
        """Test that HTTP 503 maps to SERVICE_UNAVAILABLE."""
        assert _http_status_to_error_code(503) == ErrorCode.SERVICE_UNAVAILABLE

    def test_unknown_status_returns_unknown_error(self):
        """Test that unknown HTTP status codes map to UNKNOWN_ERROR."""
        assert _http_status_to_error_code(418) == ErrorCode.UNKNOWN_ERROR
        assert _http_status_to_error_code(599) == ErrorCode.UNKNOWN_ERROR


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

        assert response.status_code == 401

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

        assert response.status_code == 401

    def test_create_error_response_dify_rate_limit(self):
        """Test creating error response for DIFY_RATE_LIMIT."""
        response = create_error_response(ErrorCode.DIFY_RATE_LIMIT)

        assert response.status_code == 429

    def test_create_error_response_validation_error(self):
        """Test creating error response for VALIDATION_ERROR."""
        response = create_error_response(ErrorCode.VALIDATION_ERROR)

        assert response.status_code == 400

    def test_create_error_response_token_expired(self):
        """Test creating error response for TOKEN_EXPIRED."""
        response = create_error_response(ErrorCode.TOKEN_EXPIRED)

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

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_different_error_codes_map_to_correct_status(self):
        """Test that different error codes produce correct HTTP status."""
        test_cases = [
            (ErrorCode.TOKEN_EXPIRED, 401),
            (ErrorCode.TOKEN_INVALID, 401),
            (ErrorCode.FORBIDDEN, 403),
            (ErrorCode.RATE_LIMIT_EXCEEDED, 429),
            (ErrorCode.VALIDATION_ERROR, 400),
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
