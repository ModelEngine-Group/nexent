# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""
FastAPI application factory with common configurations and exception handlers.
"""

import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from backend.http.server.exception_handlers import register_exception_handlers
from backend.http.server.health import install_health_contract

try:
    from infrastructure.trace.bootstrap import monitoring_manager
except ImportError:
    monitoring_manager = None

logger = logging.getLogger(__name__)


def _with_ops_monitoring(lifespan):
    @asynccontextmanager
    async def combined(app):
        from infrastructure.monitoring.runtime import producer_lifespan

        async with AsyncExitStack() as stack:
            await stack.enter_async_context(producer_lifespan())
            state = await stack.enter_async_context(lifespan(app)) if lifespan is not None else None
            yield state

    return combined


def create_app(
    title: str = "Nexent API",
    description: str = "",
    version: str = "1.0.0",
    root_path: str = "/api",
    cors_origins: list = None,
    cors_methods: list = None,
    enable_monitoring: bool = True,
    lifespan=None,
    gateway_identity_audience=None,
    internal_runtime_request=None,
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
        gateway_identity_audience: Expected audience for signed Gateway identities
        internal_runtime_request: Optional predicate for scoped Runtime service requests

    Returns:
        Configured FastAPI application
    """
    if enable_monitoring:
        from contracts.constants.environment import OPS_MONITORING_ENABLED

        if OPS_MONITORING_ENABLED:
            lifespan = _with_ops_monitoring(lifespan)

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
    if gateway_identity_audience:
        from gateway.downstream.middleware import GatewayIdentityMiddleware

        app.add_middleware(
            GatewayIdentityMiddleware, audience=gateway_identity_audience,
            internal_runtime_request=internal_runtime_request,
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
