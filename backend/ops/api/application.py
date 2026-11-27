# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compose operations APIs while preserving minimal health startup."""

from fastapi import FastAPI

from contracts.constants.environment import APP_VERSION, OPS_MONITORING_ENABLED
from backend.http.server.exception_handlers import register_exception_handlers
from gateway.identity.middleware import GatewayIdentityMiddleware
from management.api.permission.ops_access import router as access_router
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
    # Outermost: /nb responses leave this process in the published partner envelope.
    from ops.api.northbound_envelope import NorthboundEnvelopeMiddleware

    application.add_middleware(NorthboundEnvelopeMiddleware)
    application.include_router(system_configuration_router)
    if trajectory_enabled():
        from ops.api.trajectory import router as trajectory_router
        from ops.api.trajectory_directory import router as directory_router

        application.include_router(trajectory_router)
        application.include_router(directory_router)
    else:
        from ops.api.trajectory import imports_router

        application.include_router(imports_router, prefix="/trajectory")
    if OPS_MONITORING_ENABLED:
        from ops.api.monitoring import ops_router

        application.include_router(ops_router)
        # Northbound mirror: the same handlers under /nb resolve API-key
        # principals (ops_principal) and are wrapped into the partner
        # envelope by NorthboundEnvelopeMiddleware. Registered by the gateway
        # exposure snapshot with credential_kinds=["api_key"].
        application.include_router(ops_router, prefix="/nb", include_in_schema=False)
    return application


app = create_app()
