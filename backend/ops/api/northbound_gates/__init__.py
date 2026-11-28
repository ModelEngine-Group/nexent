# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Northbound capability gates for the operations service.

Per the northbound exposure design, every exposed capability gets one
hand-written gate under ``/nb/v1``: the identical path-aware identity
dependency, the shared selection dependencies and the original handler
function — the business kernel stays the one service the internal session
routes use. ``nb_capability_routers`` returns every router with at least one
declared gate so the application (and the offline exposure generator) can
mount them all.
"""

from fastapi import APIRouter

from ops.api.northbound_gates.monitoring import nb_monitoring_router

__all__ = ["nb_monitoring_router", "nb_capability_routers"]


def nb_capability_routers() -> tuple[APIRouter, ...]:
    """Every northbound gate router, for mounting on the Ops application."""
    return (nb_monitoring_router,)
