# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compose operations APIs while preserving minimal health startup."""

from contracts.constants.environment import APP_VERSION
from fastapi import FastAPI
from gateway.downstream.middleware import GatewayIdentityMiddleware
from management.utils.exception_handlers import register_exception_handlers
from ops.api.access import router as access_router
from ops.api.health import router as health_router
from ops.api.system_configurations import router as system_configuration_router
from ops.lifespan import ops_lifespan, trajectory_enabled


def create_app() -> FastAPI:
    """Create an operations application and its process-local state."""
    application = FastAPI(
        title="Nexent Operations API",
        version=APP_VERSION,
        lifespan=ops_lifespan,
        root_path="/api",
    )
    application.state.ready = False
    register_exception_handlers(application)
    application.include_router(access_router)
    application.include_router(health_router)
    application.add_middleware(GatewayIdentityMiddleware, audience="ops")
    application.include_router(system_configuration_router)
    if trajectory_enabled():
        from ops.api.trajectory import router as trajectory_router
        from ops.api.trajectory_directory import router as directory_router

        application.include_router(trajectory_router)
        application.include_router(directory_router)
    return application


app = create_app()
