"""Unified control plane: /health, /_reset, /_mock/*, /_wire-log.

The AIDP sub-application mounted at the service root keeps its own /health,
/_reset and /_mock/fail-next endpoints, but the routes registered here take
precedence (parent routes match before the root mount). AIDP operations are
forwarded to the sub-app in-process through httpx.ASGITransport (async —
httpx provides no sync ASGI transport), so the AIDP mock file itself stays
untouched.
"""
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

    @router.post("/_reset")
    async def reset(body: Optional[ResetBody] = None) -> Dict[str, Any]:
        requested = body.services if body and body.services else _known_services()
        reset_done: List[str] = []
        for service in requested:
            if service == "aidp":
                await _aidp_request(aidp_app, "POST", "/_reset")
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
            await _aidp_request(aidp_app, "POST", "/_mock/fail-reset")
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
        return {"records": wire_log.query(service=service, limit=limit)}

    @router.post("/_wire-log/clear")
    def wire_log_clear() -> Dict[str, Any]:
        wire_log.clear()
        return {"cleared": True}

    return router
