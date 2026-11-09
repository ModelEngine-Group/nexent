# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private Gateway identity lookup protected by body-bound service signatures."""

import json

from fastapi import APIRouter, HTTPException, Request

from thread_management.management import config_thread_manager
from service_common.service_identity.gateway import IdentityError, verify_lookup
from management.services.permission.identity.gateway_lookup import resolve_gateway_identity
from nexent.core.concurrency import ManagedTaskSpec

router = APIRouter()


@router.post("/internal/identity/resolve", include_in_schema=False)
async def resolve_identity(request: Request):
    # Bound internal payload size before buffering; Gateway never sends file bodies here.
    parts, size = [], 0
    async for part in request.stream():
        size += len(part)
        if size > 16 * 1024:
            raise HTTPException(status_code=413, detail="Identity query too large")
        parts.append(part)
    body = b"".join(parts)
    try:
        verify_lookup(request.headers.get("x-nexent-service-token", ""), body)
        query = json.loads(body)
        if not isinstance(query, dict):
            raise ValueError()
        return await config_thread_manager.run(
            "control-io", ManagedTaskSpec(task_name="gateway-identity-lookup", owner=__name__),
            resolve_gateway_identity, query,
        )
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail="Identity lookup rejected") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid identity query") from exc
    except Exception:
        # Persistence exceptions can contain SQL parameters, including opaque keys.
        raise HTTPException(status_code=503, detail="Identity service unavailable") from None
