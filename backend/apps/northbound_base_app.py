"""
Northbound API with A2A support.

This module combines northbound app with A2A server endpoints.
"""
import base64
import hashlib
import json
import logging
from typing import Annotated, Any, Dict
from http import HTTPStatus

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from apps.app_factory import create_app
from .northbound_app import router as northbound_router


class A2AServerSettings(BaseModel):
    """A2A Server settings for an agent."""
    model_config = {"extra": "forbid"}

    is_enabled: Annotated[bool | None, Field(strict=True)] = False
    card_overrides: Dict[str, Any] | None = None


from services.northbound_service import NorthboundContext
from services.a2a_server_service import (
    a2a_server_service,
    EndpointNotFoundError,
    AgentNotEnabledError,
    TaskNotFoundError,
    UnsupportedOperationError,
    A2AServerServiceError,
)
from database import a2a_agent_db

logger = logging.getLogger("northbound_base_app")

# Create FastAPI app with common configurations
northbound_app = create_app(
    title="Nexent Northbound API",
    description="Northbound APIs for partners",
    version="1.0.0",
    cors_methods=["GET", "POST", "PUT", "DELETE"],
    enable_monitoring=False  # Disable monitoring for northbound API if not needed
)

northbound_app.include_router(northbound_router)


# =============================================================================
# A2A Server Endpoints (Combined into northbound_base_app)
# =============================================================================

# Create separate router for A2A endpoints
a2a_router = APIRouter(prefix="/nb/a2a", tags=["Northbound A2A"])


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request payload."""
    jsonrpc: str = "2.0"
    method: str
    params: Dict[str, Any] | None = {}
    id: Any | None = None


@a2a_router.get("/{endpoint_id}/.well-known/agent-card.json")
async def get_agent_card(
    endpoint_id: str,
    request: Request,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None
):
    """Get Agent Card for A2A discovery.

    Standard A2A 1.0 discovery endpoint at /nb/a2a/{endpoint_id}/.well-known/agent-card.json.
    Supports HTTP caching via ETag.
    """
    try:
        base_url = str(request.base_url).rstrip("/")

        card = a2a_server_service.get_agent_card(
            endpoint_id=endpoint_id,
            base_url=base_url,
            use_northbound=True
        )

        card_json = json.dumps(card, sort_keys=True)
        etag = hashlib.md5(card_json.encode()).hexdigest()

        if if_none_match == etag:
            return JSONResponse(status_code=304)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=card,
            headers={
                "Cache-Control": "public, max-age=3600",
                "ETag": etag,
            }
        )

    except EndpointNotFoundError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Get agent card failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get agent card"
        )


@a2a_router.post("/{endpoint_id}/v1")
async def jsonrpc_handler(
    endpoint_id: str,
    payload: JSONRPCRequest,
    request: Request,
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
    a2a_extensions: Annotated[str | None, Header(alias="A2A-Extensions")] = None,
):
    """JSON-RPC 2.0 endpoint for A2A protocol.

    Supported methods:
    - SendMessage: Send a synchronous message
    - SendStreamingMessage: Send a streaming message (returns SSE)
    - GetTask: Retrieve task information
    """
    try:
        from .northbound_app import _get_northbound_context
        ctx = await _get_northbound_context(request)

        if payload.method == "SendMessage":
            result = await _handle_jsonrpc_send(endpoint_id, payload.params or {}, ctx)
            return JSONResponse({
                "jsonrpc": "2.0",
                "result": result,
                "id": payload.id
            })
        elif payload.method == "SendStreamingMessage":
            return await _handle_jsonrpc_stream(endpoint_id, payload.params or {}, ctx, payload.id)
        elif payload.method == "GetTask":
            result = _handle_jsonrpc_get_task(endpoint_id, payload.params or {}, ctx)
            return JSONResponse({
                "jsonrpc": "2.0",
                "result": result,
                "id": payload.id
            })
        else:
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Method not found: {payload.method}"},
                "id": payload.id
            })

    except EndpointNotFoundError as e:
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": "Endpoint not found"},
            "id": payload.id
        })
    except TaskNotFoundError as e:
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32001, "message": "Task not found"},
            "id": payload.id
        })
    except UnsupportedOperationError as e:
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32004, "message": "Unsupported operation"},
            "id": payload.id
        })
    except Exception as e:
        logger.error(f"JSON-RPC handler error for endpoint {endpoint_id}: {e}", exc_info=True)
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32603, "message": "Internal error"},
            "id": payload.id
        })


async def _handle_jsonrpc_send(endpoint_id: str, params: Dict[str, Any], ctx: NorthboundContext) -> Dict[str, Any]:
    """Handle JSON-RPC SendMessage method.
    
    JSON-RPC params structure is the same as REST message body:
    {
        "message": {...},
        "history": [...],
        "configuration": {...},
        "metadata": {...}
    }
    Reuse the same format as REST for consistent parsing.
    """
    # params already contains {message, history, configuration, metadata}
    # Reuse REST message handler by passing the entire params as message
    result = await a2a_server_service.handle_message_send(
        endpoint_id=endpoint_id,
        message=params,  # Pass full params as message for unified parsing
        token_id=ctx.token_id,
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id
    )
    return result


def _handle_jsonrpc_get_task(endpoint_id: str, params: Dict[str, Any], ctx: NorthboundContext) -> Dict[str, Any]:
    """Handle JSON-RPC GetTask method."""
    task_id = params.get("id")
    if not task_id:
        raise A2AServerServiceError("Missing required parameter: id")

    result = a2a_server_service.get_task(
        task_id=task_id,
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id
    )
    return result


async def _handle_jsonrpc_stream(endpoint_id: str, params: Dict[str, Any], ctx: NorthboundContext, jsonrpc_id: Any):
    """Handle JSON-RPC SendStreamingMessage method - returns SSE stream.

    JSON-RPC params structure is the same as REST message body:
    {
        "message": {...},
        "history": [...],
        "configuration": {...},
        "metadata": {...}
    }
    Reuse the same format as REST for consistent parsing.
    """
    # params already contains {message, history, configuration, metadata}
    # Reuse REST stream handler by passing the entire params as message
    message = params  # Pass full params as message for unified parsing

    def wrap_jsonrpc(event: Dict[str, Any]) -> Dict[str, Any]:
        """Wrap event in JSON-RPC 2.0 envelope."""
        return {
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "result": event
        }

    async def generate_sse():
        try:
            async for event in a2a_server_service.handle_message_stream(
                endpoint_id=endpoint_id,
                message=message,
                token_id=ctx.token_id,
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id
            ):
                wrapped = wrap_jsonrpc(event)
                yield f"data: {json.dumps(wrapped)}\n\n"
        except Exception as e:
            logger.error(f"SSE stream error: {e}", exc_info=True)
            error_event = {
                "jsonrpc": "2.0",
                "id": jsonrpc_id,
                "error": {"code": -32603, "message": str(e)}
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# =============================================================================
# REST Endpoints (Simplified Path)
# =============================================================================

@a2a_router.post("/{endpoint_id}/message:send")
async def rest_message_send(
    endpoint_id: str,
    message: Dict[str, Any],
    request: Request,
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
):
    """REST endpoint - send message synchronously.

    Requires authentication via Authorization header.
    """
    try:
        from .northbound_app import _get_northbound_context
        ctx = await _get_northbound_context(request)

        result = await a2a_server_service.handle_message_send(
            endpoint_id=endpoint_id,
            message=message,
            token_id=ctx.token_id,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id
        )

        return JSONResponse(status_code=HTTPStatus.OK, content=result)

    except EndpointNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except AgentNotEnabledError as e:
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        logger.error(f"REST message send failed: {e}", exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to send message")


@a2a_router.post("/{endpoint_id}/message:stream")
async def rest_message_stream(
    endpoint_id: str,
    message: Dict[str, Any],
    request: Request,
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
):
    """REST endpoint - send message with streaming response (SSE).

    Returns SSE stream. Requires authentication.
    """
    try:
        from .northbound_app import _get_northbound_context
        ctx = await _get_northbound_context(request)

        async def generate_sse():
            try:
                async for event in a2a_server_service.handle_message_stream(
                    endpoint_id=endpoint_id,
                    message=message,
                    token_id=ctx.token_id,
                    user_id=ctx.user_id,
                    tenant_id=ctx.tenant_id
                ):
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as e:
                logger.error(f"SSE stream error: {e}", exc_info=True)
                fail_payload = json.dumps({
                    "statusUpdate": {
                        "taskId": "",
                        "status": {
                            "state": "TASK_STATE_FAILED",
                            "message": "An internal error occurred while processing the stream."
                        }
                    }
                })
                yield f"data: {fail_payload}\n\n"

        return StreamingResponse(
            generate_sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except EndpointNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except AgentNotEnabledError as e:
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        logger.error(f"REST message stream failed: {e}", exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to stream message")


# =============================================================================
# Task Management Endpoints
# =============================================================================

@a2a_router.get("/{endpoint_id}/tasks/{task_id}")
async def rest_get_task(
    endpoint_id: str,
    task_id: str,
    request: Request,
    historyLength: Annotated[int | None, Query(ge=-1, description="Number of history messages to include")] = None,
):
    """REST endpoint - get task details in A2A standard format.

    Query parameters:
    - historyLength: Number of history messages to include (-1 for all, 0 for none)
    """
    try:
        from .northbound_app import _get_northbound_context
        ctx: NorthboundContext = await _get_northbound_context(request)

        task = a2a_server_service.get_task(
            task_id=task_id,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id
        )

        return JSONResponse({"task": task})

    except TaskNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"REST get task failed: {e}", exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to get task")


# Include A2A router into main app
northbound_app.include_router(a2a_router)