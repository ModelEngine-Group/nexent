# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compose the operations API without initializing business infrastructure."""

from fastapi import FastAPI

from contracts.constants.environment import APP_VERSION
from management.utils.exception_handlers import register_exception_handlers
from ops.api.access import router as access_router
from ops.api.health import router as health_router
from ops.lifespan import ops_lifespan


def create_app() -> FastAPI:
    """Create an isolated operations application and its process-local state."""
    application = FastAPI(
        title='Nexent Operations API',
        version=APP_VERSION,
        lifespan=ops_lifespan,
    )
    application.state.ready = False
    register_exception_handlers(application)
    application.include_router(access_router)
    application.include_router(health_router)
    return application


app = create_app()
