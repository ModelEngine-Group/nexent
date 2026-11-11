# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""
FastAPI application factory with common configurations and exception handlers.
"""

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from management.utils.exception_handlers import register_exception_handlers
from management.utils.health import install_health_contract

try:
    from infrastructure.observability.bootstrap import monitoring_manager
except ImportError:
    monitoring_manager = None

logger = logging.getLogger(__name__)


def create_app(
    title: str = "Nexent API",
    description: str = "",
    version: str = "1.0.0",
    root_path: str = "/api",
    cors_origins: list = None,
    cors_methods: list = None,
    enable_monitoring: bool = True,
    lifespan=None,
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
        lifespan: Optional FastAPI lifespan context manager

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title=title,
        description=description,
        version=version,
        root_path=root_path,
        lifespan=lifespan,
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

    # Process health endpoints never poll external dependencies.
    install_health_contract(app)

    # Initialize monitoring if enabled
    if enable_monitoring:
        try:
            if monitoring_manager is None:
                raise ImportError("Monitoring utilities not available")
            monitoring_manager.setup_fastapi_app(app)
        except ImportError:
            logger.warning("Monitoring utilities not available")

    return app


class ModelCredentialRoute(APIRoute):
    """Keep input validation diagnostics from reflecting model credential values."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def credential_safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                details = [{key: value for key, value in item.items() if key in {"loc", "msg", "type"}}
                           for item in error.errors()]
                return JSONResponse(status_code=422, content={"detail": details})

        return credential_safe_handler
