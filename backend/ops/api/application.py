# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compose optional trajectory APIs while preserving minimal health startup."""

from contracts.constants.environment import APP_VERSION
from fastapi import FastAPI
from ops.api.health import router as health_router
from ops.lifespan import ops_lifespan, trajectory_enabled


def create_app() -> FastAPI:
    """Create an operations application and its process-local state."""
    application = FastAPI(
        title='Nexent Operations API',
        version=APP_VERSION,
        lifespan=ops_lifespan,
        root_path="/api",
    )
    application.state.ready = False
    application.include_router(health_router)
    if trajectory_enabled():
        from ops.api.trajectory import router as trajectory_router
        from ops.api.trajectory_directory import router as directory_router

        application.include_router(trajectory_router)
        application.include_router(directory_router)
    return application


app = create_app()
