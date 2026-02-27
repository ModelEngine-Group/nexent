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

from consts.error_code import ErrorCode
from consts.error_message import ErrorMessage
from consts.exceptions import AppException

logger = logging.getLogger(__name__)


def _http_status_to_error_code(status_code: int) -> ErrorCode:
    """Map HTTP status codes to internal error codes for backward compatibility."""
    mapping = {
        400: ErrorCode.VALIDATION_ERROR,
        401: ErrorCode.UNAUTHORIZED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.RESOURCE_NOT_FOUND,
        429: ErrorCode.RATE_LIMIT_EXCEEDED,
        500: ErrorCode.INTERNAL_ERROR,
        502: ErrorCode.SERVICE_UNAVAILABLE,
        503: ErrorCode.SERVICE_UNAVAILABLE,
    }
    return mapping.get(status_code, ErrorCode.UNKNOWN_ERROR)


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
        except AppException as exc:
            # Log the error with trace ID
            logger.error(
                f"[{trace_id}] AppException: {exc.error_code.value} - {exc.message}",
                extra={"trace_id": trace_id,
                       "error_code": exc.error_code.value}
            )

            # Use HTTP status from error code mapping, default to 500
            http_status = exc.http_status

            return JSONResponse(
                status_code=http_status,
                content={
                    "code": exc.error_code.value,
                    "message": exc.message,
                    "trace_id": trace_id,
                    "details": exc.details if exc.details else None
                }
            )
        except HTTPException as exc:
            # Handle FastAPI HTTPException for backward compatibility
            # Map HTTP status codes to error codes
            error_code = _http_status_to_error_code(exc.status_code)

            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "code": error_code.value,
                    "message": exc.detail,
                    "trace_id": trace_id
                }
            )
        except Exception as exc:
            # Log the full exception with traceback
            logger.error(
                f"[{trace_id}] Unhandled exception: {str(exc)}",
                exc_info=True,
                extra={"trace_id": trace_id}
            )

            # Return generic error response
            return JSONResponse(
                status_code=200,
                content={
                    "code": ErrorCode.UNKNOWN_ERROR.value,
                    "message": ErrorMessage.get_message(ErrorCode.UNKNOWN_ERROR),
                    "trace_id": trace_id
                }
            )


def create_error_response(
    error_code: ErrorCode,
    message: str = None,
    trace_id: str = None,
    details: dict = None
) -> JSONResponse:
    """
    Create a standardized error response.

    Args:
        error_code: The error code
        message: Optional custom message (defaults to standard message)
        trace_id: Optional trace ID for tracking
        details: Optional additional details

    Returns:
        JSONResponse with standardized error format
    """
    return JSONResponse(
        status_code=200,
        content={
            "code": error_code.value,
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
