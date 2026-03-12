"""
Global exception handler middleware.

This middleware provides centralized error handling for the FastAPI application.
It catches all exceptions and returns a standardized JSON response.
"""

import logging
import traceback
import uuid
from typing import Callable

from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from consts.error_code import ErrorCode, ERROR_CODE_HTTP_STATUS
from consts.error_message import ErrorMessage

logger = logging.getLogger(__name__)


def _http_status_to_error_code(status_code: int) -> ErrorCode:
    """Map HTTP status codes to internal error codes for backward compatibility."""
    mapping = {
        400: ErrorCode.COMMON_VALIDATION_ERROR,
        401: ErrorCode.COMMON_UNAUTHORIZED,
        403: ErrorCode.COMMON_FORBIDDEN,
        404: ErrorCode.COMMON_RESOURCE_NOT_FOUND,
        429: ErrorCode.COMMON_RATE_LIMIT_EXCEEDED,
        500: ErrorCode.SYSTEM_INTERNAL_ERROR,
        502: ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
        503: ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
    }
    return mapping.get(status_code, ErrorCode.SYSTEM_UNKNOWN_ERROR)


class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """
    Global exception handler middleware.

    This middleware catches all exceptions and returns a standardized response:
    - For AppException: returns the error code and message
    - For other exceptions: logs the error and returns a generic error response
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate trace ID for request tracking
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id

        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            # Check if it's an AppException by looking for the error_code attribute
            # This handles both import path variations (backend.consts.exceptions vs consts.exceptions)
            if hasattr(exc, 'error_code'):
                # This is an AppException - get http_status from mapping
                logger.error(
                    f"[{trace_id}] AppException: {exc.error_code.value} - {exc.message}",
                    extra={"trace_id": trace_id,
                           "error_code": exc.error_code.value}
                )

                # Use HTTP status from error code mapping, default to 500
                # Try to get http_status property first, then fall back to ERROR_CODE_HTTP_STATUS mapping
                if hasattr(exc, 'http_status'):
                    http_status = exc.http_status
                else:
                    http_status = ERROR_CODE_HTTP_STATUS.get(
                        exc.error_code, 500)

                return JSONResponse(
                    status_code=http_status,
                    content={
                        "code": exc.error_code.value,  # Keep as string to preserve leading zeros
                        "message": exc.message,
                        "trace_id": trace_id,
                        "details": exc.details if exc.details else None
                    }
                )
            elif isinstance(exc, HTTPException):
                # Handle FastAPI HTTPException for backward compatibility
                # Map HTTP status codes to error codes
                error_code = _http_status_to_error_code(exc.status_code)

                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "code": error_code.value,  # Keep as string to preserve leading zeros
                        "message": exc.detail,
                        "trace_id": trace_id
                    }
                )
            else:
                # Log the full exception with traceback
                logger.error(
                    f"[{trace_id}] Unhandled exception: {str(exc)}",
                    exc_info=True,
                    extra={"trace_id": trace_id}
                )

                # Return generic error response with proper HTTP 500 status
                # Using mixed mode: HTTP status code + business error code
                return JSONResponse(
                    status_code=500,
                    content={
                        "code": ErrorCode.SYSTEM_INTERNAL_ERROR.value,
                        "message": ErrorMessage.get_message(ErrorCode.SYSTEM_INTERNAL_ERROR),
                        "trace_id": trace_id,
                        "details": None
                    }
                )


def create_error_response(
    error_code: ErrorCode,
    message: str = None,
    trace_id: str = None,
    details: dict = None,
    http_status: int = None
) -> JSONResponse:
    """
    Create a standardized error response with mixed mode (HTTP status + business error code).

    Args:
        error_code: The error code
        message: Optional custom message (defaults to standard message)
        trace_id: Optional trace ID for tracking
        details: Optional additional details
        http_status: Optional HTTP status code (defaults to mapping from error_code)

    Returns:
        JSONResponse with standardized error format
    """
    # Use provided http_status or get from error code mapping
    status = http_status if http_status else ERROR_CODE_HTTP_STATUS.get(
        error_code, 500)

    return JSONResponse(
        status_code=status,
        content={
            "code": error_code.value,  # Keep as string to preserve leading zeros
            "message": message or ErrorMessage.get_message(error_code),
            "trace_id": trace_id,
            "details": details
        }
    )


def create_success_response(
    data: any = None,
    message: str = "OK",
    trace_id: str = None
) -> JSONResponse:
    """
    Create a standardized success response.

    Args:
        data: The response data
        message: Optional success message
        trace_id: Optional trace ID for tracking

    Returns:
        JSONResponse with standardized success format
    """
    return JSONResponse(
        status_code=200,
        content={
            "code": 0,  # 0 indicates success
            "message": message,
            "data": data,
            "trace_id": trace_id
        }
    )
