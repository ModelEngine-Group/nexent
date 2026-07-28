"""
FastAPI application factory with common configurations and exception handlers.
"""
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from consts.exceptions import AppException, QuotaExceededError


logger = logging.getLogger(__name__)


def create_app(
    title: str = "Nexent API",
    description: str = "",
    version: str = "1.0.0",
    root_path: str = "/api",
    cors_origins: list = None,
    cors_methods: list = None,
    enable_monitoring: bool = True,
) -> FastAPI:
    """
    Create a FastAPI application with common configurations.

    Args:
        title: API title
        description: API description
        version: API version
        root_path: Root path for the API
        cors_origins: List of allowed CORS origins (default: ["*"])
        cors_methods: List of allowed CORS methods (default: ["*"])
        enable_monitoring: Whether to enable monitoring

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title=title,
        description=description,
        version=version,
        root_path=root_path
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=cors_methods or ["*"],
        allow_headers=["*"],
    )

    # Register exception handlers
    register_exception_handlers(app)

    # Initialize monitoring if enabled
    if enable_monitoring:
        try:
            from utils.monitoring import monitoring_manager
            monitoring_manager.setup_fastapi_app(app)
        except ImportError:
            logger.warning("Monitoring utilities not available")

    return app


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register common exception handlers for the FastAPI application.

    Args:
        app: FastAPI application instance
    """

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        logger.error(f"HTTPException: {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            content={"message": exc.detail},
        )

    @app.exception_handler(AppException)
    async def app_exception_handler(request, exc):
        logger.error(f"AppException: {exc.error_code.value} - {exc.message}")
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "code": exc.error_code.value,
                "message": exc.message,
                "details": exc.details if exc.details else None
            },
        )

    @app.exception_handler(QuotaExceededError)
    async def quota_exceeded_exception_handler(request, exc):
        logger.warning("QuotaExceededError: %s", exc)
        return JSONResponse(
            status_code=413,
            content={
                "error": "TenantStorageFull",
                "message": str(exc),
                "usage_bytes": exc.usage_bytes,
                "hard_limit_bytes": exc.hard_limit_bytes,
                "exceeded_by_bytes": exc.exceeded_by_bytes,
            },
        )

    # ---- AIDP permission subsystem exceptions (v7.1) ----
    # These are domain exceptions (inherit from plain Exception) that map to
    # HTTP status codes per v7.1 design. Without explicit handlers they would
    # fall through to the generic handler below and surface as 500, hiding
    # the real error from the client.
    try:
        from ext_components.aidp.consts.aidp_exceptions import (
            AidpKbNotFoundError,
            AidpKbPermissionDeniedError,
            AidpKbConflictError,
            AidpKbSyncError,
            AidpGroupValidationError,
        )

        @app.exception_handler(AidpKbNotFoundError)
        async def aidp_kb_not_found_handler(request, exc):
            logger.warning("AidpKbNotFoundError: %s", exc)
            return JSONResponse(
                status_code=404,
                content={"message": str(exc), "code": "AIDP_KB_NOT_FOUND", "kb_id": exc.kb_id},
            )

        @app.exception_handler(AidpKbPermissionDeniedError)
        async def aidp_permission_denied_handler(request, exc):
            logger.warning("AidpKbPermissionDeniedError: user=%s kb=%s required=%s", exc.user_id, exc.kb_id, exc.required)
            return JSONResponse(
                status_code=403,
                content={
                    "message": str(exc),
                    "code": "AIDP_PERMISSION_DENIED",
                    "kb_id": exc.kb_id,
                    "required": exc.required,
                },
            )

        @app.exception_handler(AidpKbConflictError)
        async def aidp_conflict_handler(request, exc):
            logger.warning("AidpKbConflictError: %s", exc)
            return JSONResponse(
                status_code=409,
                content={"message": str(exc), "code": "AIDP_KB_CONFLICT", "kb_id": exc.kb_id},
            )

        @app.exception_handler(AidpKbSyncError)
        async def aidp_sync_error_handler(request, exc):
            logger.error("AidpKbSyncError: %s", exc)
            return JSONResponse(
                status_code=502,
                content={"message": str(exc), "code": "AIDP_SYNC_ERROR", "operation": exc.operation},
            )

        @app.exception_handler(AidpGroupValidationError)
        async def aidp_group_validation_handler(request, exc):
            logger.warning("AidpGroupValidationError: %s", exc)
            return JSONResponse(
                status_code=400,
                content={
                    "message": str(exc),
                    "code": "AIDP_GROUP_VALIDATION",
                    "invalid_ids": exc.invalid_ids,
                },
            )
    except ImportError:
        # AIDP subsystem not installed in this deployment; safe to skip
        logger.debug("AIDP exception classes not available, skipping AIDP exception handlers")

    @app.exception_handler(Exception)
    async def generic_exception_handler(request, exc):
        # Don't catch AppException - it has its own handler
        if isinstance(exc, AppException):
            return await app_exception_handler(request, exc)

        # Handle NexentCapabilityError with a friendly message
        from adapters.exception import NexentCapabilityError as _NCE

        if isinstance(exc, _NCE):
            logger.warning(f"NexentCapabilityError: {exc}")
            return JSONResponse(
                status_code=400,
                content={"message": str(exc)},
            )

        logger.error(f"Generic Exception: {exc}")
        return JSONResponse(
            status_code=500,
            content={"message": "Internal server error, please try again later."},
        )
