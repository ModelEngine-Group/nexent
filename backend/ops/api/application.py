# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compose the operations API without initializing business infrastructure."""

from fastapi import FastAPI

from contracts.constants.environment import APP_VERSION
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
    application.include_router(health_router)
    return application


app = create_app()
