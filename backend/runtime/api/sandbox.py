# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Owner-local sandbox tool callbacks with scoped invocation capabilities."""

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from infrastructure.concurrency import runtime_thread_manager
from runtime.sandbox_services import current_callback_registry

from nexent.core.agents.sandbox import _serialize_tool_bridge_value
from nexent.core.agents.sandbox_callbacks import SandboxCallbackAuthorizationError, SandboxCallbackContextError
from nexent.core.concurrency import ManagedTaskSpec


router = APIRouter(prefix='/internal/sandbox', include_in_schema=False)


@router.post('/tool-invoke')
async def invoke_tool(request: Request):
    registry = current_callback_registry()
    if registry is None:
        raise HTTPException(status_code=404, detail='Sandbox callbacks are disabled')
    authorization = request.headers.get('authorization', '')
    try:
        registry.authorize(authorization)
    except SandboxCallbackAuthorizationError:
        raise HTTPException(status_code=403, detail='Invalid callback capability') from None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024 * 1024:
            raise HTTPException(status_code=413, detail='Callback body exceeds limit')
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise TypeError('Callback must be an object')
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='Invalid callback body') from None
    try:
        result = await runtime_thread_manager.run(
            'sandbox', ManagedTaskSpec(task_name='sandbox-host-callback', owner='runtime.api.sandbox'),
            registry.invoke, authorization, payload,
        )
        return {'result': _serialize_tool_bridge_value(result)}
    except SandboxCallbackAuthorizationError:
        raise HTTPException(status_code=403, detail='Expired callback capability') from None
    except SandboxCallbackContextError:
        raise HTTPException(status_code=403, detail='Unknown callback context or tool') from None
    except Exception as exc:
        return JSONResponse(status_code=500, content={'error': str(exc)})
