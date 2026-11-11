# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound capability gates: hand-written thin routes over shared services.

Per the northbound exposure design (§5.6, Spring-style double-gate), each
exposed capability gets one hand-written gate function under ``/nb/v1``:
the identical ``unified_identity`` declaration, the path-resolved envelope and
the action-policy dependencies (audit, usage accounting). The business kernel
stays the one service function shared with the internal route.

Gates are grouped by domain. ``nb_capability_routers`` returns every router
with at least one gate so the Management application can mount them all.
"""

from fastapi import APIRouter

from management.api.northbound_gates.conversations import nb_conversation_router
from management.api.northbound_gates.automations import nb_automation_router
from management.api.northbound_gates.files import nb_file_router

__all__ = [
    "nb_conversation_router",
    "nb_automation_router",
    "nb_file_router",
    "nb_capability_routers",
]


def nb_capability_routers() -> tuple[APIRouter, ...]:
    """Every northbound gate router, for mounting on the Management app."""
    return (nb_conversation_router, nb_automation_router, nb_file_router)
