import logging
from http import HTTPStatus
from typing import Optional, Dict, Any
import uuid

from fastapi import APIRouter, Body, Header, Request, HTTPException, Query
from fastapi.responses import JSONResponse

from consts.exceptions import LimitExceededError, UnauthorizedError
from services.northbound_service import (
    NorthboundContext,
    get_conversation_history,
    list_conversations,
    start_streaming_chat,
    stop_chat,
    get_agent_info_list,
    update_conversation_title,
)

from utils.auth_utils import validate_bearer_token, get_user_and_tenant_by_access_key


router = APIRouter(prefix="/nb/v1", tags=["northbound"])


async def _get_northbound_context(request: Request) -> NorthboundContext:
    """
    Build northbound context from request.

    Authentication: Bearer Token (API Key) in Authorization header
    - Authorization: Bearer <access_key>

    The user_id and tenant_id are derived from the access_key by querying
    user_token_info_t and user_tenant_t tables.

    Optional headers:
    - X-Request-Id: Request ID, generated if not provided
    """
    # 1. Validate Bearer Token and extract access_key
    try:
        auth_header = request.headers.get("Authorization")
        is_valid, token_info = validate_bearer_token(auth_header)

        if not is_valid or not token_info:
            raise HTTPException(
                status_code=HTTPStatus.UNAUTHORIZED,
                detail="Invalid or missing bearer token"
            )

        # Extract access_key from the token
        access_key = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else auth_header

        # Get user_id and tenant_id from access_key
        user_tenant_info = get_user_and_tenant_by_access_key(access_key)
        resolved_user_id = user_tenant_info.get("user_id")
        resolved_tenant_id = user_tenant_info.get("tenant_id")
        token_id = user_tenant_info.get("token_id")

    except HTTPException:
        raise
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except UnauthorizedError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(e)
        )
    except Exception as e:
        logging.error(f"Failed to validate bearer token: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="Unauthorized: invalid API key"
        )

    if not resolved_user_id:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Missing user information for this access key"
        )

    if not resolved_tenant_id:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Missing tenant information for this access key"
        )

    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())

    # Get authorization header if present, otherwise use a placeholder
    auth_header_value = request.headers.get("Authorization", "Bearer placeholder")

    return NorthboundContext(
        request_id=request_id,
        tenant_id=resolved_tenant_id,
        user_id=resolved_user_id,
        authorization=auth_header_value,
        token_id=token_id,
    )


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "northbound-api"}


@router.post("/chat/run")
async def run_chat(
    request: Request,
    conversation_id: Optional[int] = Body(None, embed=True),
    agent_name: str = Body(..., embed=True),
    query: str = Body(..., embed=True),
    meta_data: Optional[Dict[str, Any]] = Body(None, embed=True),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await start_streaming_chat(
            ctx=ctx,
            conversation_id=conversation_id,
            agent_name=agent_name,
            query=query,
            meta_data=meta_data,
            idempotency_key=idempotency_key,
        )
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to run chat: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/chat/stop/{conversation_id}")
async def stop_chat_stream(
    request: Request,
    conversation_id: int,
    meta_data: Optional[str] = Query(None, description="Optional metadata as JSON string"),
):
    import json
    parsed_meta_data = None
    if meta_data:
        try:
            parsed_meta_data = json.loads(meta_data)
        except json.JSONDecodeError:
            pass
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await stop_chat(ctx=ctx, conversation_id=conversation_id, meta_data=parsed_meta_data)
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to stop chat: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/conversations/{conversation_id}")
async def get_history(
    request: Request,
    conversation_id: int,
):
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await get_conversation_history(ctx=ctx, conversation_id=conversation_id)
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to get conversation history: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/agents")
async def list_agents(request: Request):
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await get_agent_info_list(ctx=ctx)
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to list agents: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/conversations")
async def list_convs(request: Request):
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await list_conversations(ctx=ctx)
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to list conversations: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.put("/conversations/{conversation_id}/title")
async def update_convs_title(
    request: Request,
    conversation_id: int,
    title: str = Query(..., description="New title"),
    meta_data: Optional[str] = Query(None, description="Optional metadata as JSON string"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    import json
    parsed_meta_data = None
    if meta_data:
        try:
            parsed_meta_data = json.loads(meta_data)
        except json.JSONDecodeError:
            pass
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        result = await update_conversation_title(
            ctx=ctx,
            conversation_id=conversation_id,
            title=title,
            meta_data=parsed_meta_data,
            idempotency_key=idempotency_key,
        )
        headers_out = {
            "Idempotency-Key": result.get("idempotency_key", ""), "X-Request-Id": ctx.request_id}
        return JSONResponse(content=result, headers=headers_out)

    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to update conversation title: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")
