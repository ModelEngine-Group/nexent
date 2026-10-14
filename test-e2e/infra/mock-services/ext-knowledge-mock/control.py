# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unified control plane: /health, /_reset, /_mock/*, /_wire-log.

The AIDP sub-application mounted at the service root keeps its own /health,
/_reset and /_mock/fail-next endpoints, but the routes registered here take
precedence (parent routes match before the root mount). AIDP operations are
forwarded to the sub-app in-process through httpx.ASGITransport (async —
httpx provides no sync ASGI transport), so the AIDP mock file itself stays
untouched.

Reset semantics: the AIDP sub-app's own /_reset only clears KB/document
state — failure counters and the runtime knobs (processing/upload/history
page size/file faults) survive it. The unified reset therefore drives the
sub-app through its PUBLIC control endpoints to restore every knob to its
import-time default, and checks each response code: a half-completed reset
is reported as an error, never as success.
"""
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from mock_common import SERVICE_PREFIXES, FaultInjector, StateStore, WireLog


class ResetBody(BaseModel):
    # None or omitted resets everything (route sets + AIDP).
    services: Optional[List[str]] = None


class FailNextBody(BaseModel):
    service: str
    count: int = Field(default=1, ge=0)
    status: int = Field(default=503, ge=400, le=599)


class FailResetBody(BaseModel):
    service: Optional[str] = None


class LatencyBody(BaseModel):
    service: str
    delay_ms: float = Field(default=0.0, ge=0.0)


class AssetsBody(BaseModel):
    assets: List[Dict[str, Any]]


def _known_services() -> List[str]:
    return list(SERVICE_PREFIXES.keys()) + ["aidp"]


async def _aidp_request(aidp_app, method: str, path: str, params: Optional[dict] = None) -> httpx.Response:
    """In-process call into the AIDP sub-app over the ASGI interface."""
    transport = httpx.ASGITransport(app=aidp_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://aidp-internal") as client:
        return await client.request(method, path, params=params)


# AIDP reset sequence: data seeds first, then the failure counters and every
# runtime knob back to its import-time default. Query parameters are passed
# explicitly because some endpoints default to non-zero values when the
# parameter is omitted (processing-seconds defaults to 8 in the sub-app).
_AIDP_RESET_STEPS = (
    ("POST", "/_reset", {}),
    ("POST", "/_mock/fail-reset", {}),
    ("POST", "/_mock/processing-seconds", {"seconds": 0}),
    ("POST", "/_mock/history-page-size", {"size": 10}),
    ("POST", "/_mock/upload-seconds", {"seconds": 0}),
    ("POST", "/_mock/file-faults", {"query_seconds": 0, "query_fail": False, "delete_fail": False}),
)


async def _reset_aidp(aidp_app) -> None:
    """Full AIDP case isolation through public control endpoints only."""
    for method, path, params in _AIDP_RESET_STEPS:
        response = await _aidp_request(aidp_app, method, path, params=params)
        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"AIDP reset incomplete: {method} {path} returned "
                    f"{response.status_code}; retry or investigate the sub-app"
                ),
            )


def create_control_router(
    states: Dict[str, StateStore],
    faults: FaultInjector,
    wire_log: WireLog,
    aidp_app: Any,
    asset_registry: Any,
    fault_state: Any = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> Dict[str, Any]:
        services = {name: "ok" for name in states}
        if fault_state is not None:
            services["fault"] = "ok"
        try:
            response = await _aidp_request(aidp_app, "GET", "/health")
            services["aidp"] = "ok" if response.status_code == 200 else "error"
        except Exception:
            services["aidp"] = "error"
        return {"status": "ok", "services": services}

    @router.get("/_mock/identity")
    def identity() -> Dict[str, Any]:
        """Deployment metadata for attach validation; carries no secrets.

        Values come from environment variables the deployment step passes
        explicitly (compose forwards them into the container). An empty
        run_id means the instance was started without ownership metadata —
        runners must treat that as unowned and refuse write control-plane
        operations rather than resetting a foreign instance.
        """
        return {
            "service": "ext-knowledge",
            "run_id": os.environ.get("EXT_KNOWLEDGE_MOCK_RUN_ID", ""),
            "source_revision": os.environ.get("EXT_KNOWLEDGE_SOURCE_REVISION", ""),
            "build_manifest_sha256": os.environ.get("EXT_KNOWLEDGE_BUILD_MANIFEST_SHA256", ""),
        }

    @router.get("/_mock/state")
    def mock_state() -> Dict[str, Any]:
        """Control-plane snapshot (failure plan + identity) for evidence."""
        return {"faults": faults.snapshot(), "identity": identity()}

    @router.post("/_reset")
    async def reset(body: Optional[ResetBody] = None) -> Dict[str, Any]:
        requested = body.services if body and body.services else _known_services()
        # Validate the whole request before touching any state: an unknown
        # service must fail the call without leaving a partial reset behind.
        unknown = [service for service in requested if service not in _known_services()]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"unknown service {unknown[0]!r}; expected one of {_known_services()}",
            )
        reset_done: List[str] = []
        for service in requested:
            if service == "aidp":
                await _reset_aidp(aidp_app)
                reset_done.append(service)
            elif service == "fault" and fault_state is not None:
                fault_state.reset()
                faults.reset(service)
                reset_done.append(service)
            elif service in states:
                states[service].reset()
                faults.reset(service)
                reset_done.append(service)
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown service {service!r}; expected one of {_known_services()}",
                )
        return {"reset": reset_done}

    @router.post("/_mock/fail-next")
    async def fail_next(body: FailNextBody) -> Dict[str, Any]:
        if body.service == "aidp":
            response = await _aidp_request(
                aidp_app, "POST", "/_mock/fail-next",
                params={"n": body.count, "status": body.status},
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "AIDP fail-next incomplete: POST /_mock/fail-next returned "
                        f"{response.status_code}; retry or investigate the sub-app"
                    ),
                )
            return response.json()
        if body.service in SERVICE_PREFIXES:
            faults.schedule(body.service, body.count, body.status)
            return {
                "service": body.service,
                "fail_next": body.count,
                "status_code": body.status,
            }
        raise HTTPException(status_code=400, detail=f"unknown service {body.service!r}")

    @router.post("/_mock/fail-reset")
    async def fail_reset(body: Optional[FailResetBody] = None) -> Dict[str, Any]:
        service = body.service if body else None
        if service == "aidp":
            response = await _aidp_request(aidp_app, "POST", "/_mock/fail-reset")
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "AIDP fail-reset incomplete: POST /_mock/fail-reset returned "
                        f"{response.status_code}; retry or investigate the sub-app"
                    ),
                )
            return {"service": "aidp", "fail_next": 0}
        if service is not None and service not in SERVICE_PREFIXES:
            raise HTTPException(status_code=400, detail=f"unknown service {service!r}")
        faults.clear_failures(service)
        return {"service": service or "all", "fail_next": 0}

    @router.post("/_mock/latency")
    def latency(body: LatencyBody) -> Dict[str, Any]:
        if body.service == "aidp":
            raise HTTPException(
                status_code=400,
                detail="latency injection for AIDP is not supported; the AIDP "
                       "sub-app owns its own middleware",
            )
        if body.service not in SERVICE_PREFIXES:
            raise HTTPException(status_code=400, detail=f"unknown service {body.service!r}")
        faults.set_latency(body.service, body.delay_ms)
        return {"service": body.service, "delay_ms": body.delay_ms}

    @router.post("/_mock/assets")
    def declare_assets(body: AssetsBody) -> Dict[str, Any]:
        registered = asset_registry.register(body.assets)
        return {"registered": registered}

    @router.get("/_wire-log")
    def wire_log_query(
        service: Optional[str] = Query(default=None),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> Dict[str, Any]:
        # stats() lets exporters detect ring-buffer truncation: a case that
        # generated more traffic than the bound retains must not be described
        # as complete wire evidence.
        return {
            "records": wire_log.query(service=service, limit=limit),
            **wire_log.stats(),
        }

    @router.post("/_wire-log/clear")
    def wire_log_clear() -> Dict[str, Any]:
        wire_log.clear()
        return {"cleared": True}

    return router
