import logging
from http import HTTPStatus
from http.client import HTTPException
from typing import Optional, Dict
import uuid

from fastapi import APIRouter, Body, Header, Request
from fastapi.responses import JSONResponse

from consts.exceptions import UnauthorizedError, LimitExceededError, SignatureValidationError
from services.northbound_service import (
    NorthboundContext,
    get_conversation_history,
    list_conversations,
    start_streaming_chat,
    stop_chat,
    get_agent_info_list,
    update_conversation_title
)

from utils.auth_utils import get_current_user_id, validate_aksk_authentication


router = APIRouter(prefix="/nb/v1", tags=["northbound"])


def _get_header(headers: Dict[str, str], name: str) -> Optional[str]:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


async def _parse_northbound_context(request: Request) -> NorthboundContext:
    """
    Build northbound context from headers.

    - X-Access-Key: Access key for AK/SK authentication
    - X-Timestamp: Timestamp for signature validation
    - X-Signature: HMAC-SHA256 signature signed with secret key
    - Authorization: Bearer <jwt>, jwt contains sub (user_id)
    - X-Request-Id: optional, generated if not provided
    """
    # 1. Verify AK/SK signature
    try:
        # Get request body for signature verification
        request_body = ""
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body_bytes = await request.body()
                request_body = body_bytes.decode('utf-8') if body_bytes else ""
            except Exception as e:
                logging.warning(
                    f"Cannot read request body for signature verification: {e}")
                request_body = ""

        validate_aksk_authentication(request.headers, request_body)
    except (UnauthorizedError, LimitExceededError, SignatureValidationError) as e:
        raise e
    except Exception:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Internal Server Error: cannot parse northbound context")

    # 2. Parse JWT token
    auth_header = _get_header(request.headers, "Authorization")
    if not auth_header:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: No authorization header found")

    # Use auth_utils to parse JWT token
    try:
        user_id, tenant_id = get_current_user_id(auth_header)

        if not user_id:
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                                detail="Unauthorized: missing user_id in JWT token")
        if not tenant_id:
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                                detail="Unauthorized: unregistered user_id in JWT token")

    except Exception:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Internal Server Error: cannot parse JWT token")

    request_id = _get_header(
        request.headers, "X-Request-Id") or str(uuid.uuid4())

    return NorthboundContext(
        request_id=request_id,
        tenant_id=tenant_id,
        user_id=str(user_id),
        authorization=auth_header,
    )


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "northbound-api"}


@router.post("/chat/run")
async def run_chat(
    request: Request,
    conversation_id: str = Body(..., embed=True),
    agent_name: str = Body(..., embed=True),
    query: str = Body(..., embed=True),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    try:
        ctx: NorthboundContext = await _parse_northbound_context(request)
        return await start_streaming_chat(
            ctx=ctx,
            external_conversation_id=conversation_id,
            agent_name=agent_name,
            query=query,
            idempotency_key=idempotency_key,
        )
    except UnauthorizedError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: AK/SK authentication failed")
    except LimitExceededError:
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except SignatureValidationError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: invalid signature")
    except Exception:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/chat/stop/{conversation_id}")
async def stop_chat_stream(request: Request, conversation_id: str):
    try:
        ctx: NorthboundContext = await _parse_northbound_context(request)
        return await stop_chat(ctx=ctx, external_conversation_id=conversation_id)
    except UnauthorizedError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: AK/SK authentication failed")
    except LimitExceededError:
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except SignatureValidationError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: invalid signature")
    except Exception:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/conversations/{conversation_id}")
async def get_history(request: Request, conversation_id: str):
    try:
        ctx: NorthboundContext = await _parse_northbound_context(request)
        return await get_conversation_history(ctx=ctx, external_conversation_id=conversation_id)
    except UnauthorizedError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: AK/SK authentication failed")
    except LimitExceededError:
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except SignatureValidationError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: invalid signature")
    except Exception:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/agents")
async def list_agents(request: Request):
    try:
        ctx: NorthboundContext = await _parse_northbound_context(request)
        return await get_agent_info_list(ctx=ctx)
    except UnauthorizedError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: AK/SK authentication failed")
    except LimitExceededError:
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except SignatureValidationError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: invalid signature")
    except Exception:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/conversations")
async def list_convs(request: Request):
    try:
        ctx: NorthboundContext = await _parse_northbound_context(request)
        return await list_conversations(ctx=ctx)
    except UnauthorizedError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: AK/SK authentication failed")
    except LimitExceededError:
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except SignatureValidationError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: invalid signature")
    except Exception:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.put("/conversations/{conversation_id}/title")
async def update_convs_title(
    request: Request,
    conversation_id: str,
    title: str,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    try:
        ctx: NorthboundContext = await _parse_northbound_context(request)
        result = await update_conversation_title(
            ctx=ctx,
            external_conversation_id=conversation_id,
            title=title,
            idempotency_key=idempotency_key,
        )
        headers_out = {
            "Idempotency-Key": result.get("idempotency_key", ""), "X-Request-Id": ctx.request_id}
        return JSONResponse(content=result, headers=headers_out)

    except UnauthorizedError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: AK/SK authentication failed")
    except LimitExceededError:
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except SignatureValidationError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Unauthorized: invalid signature")
    except Exception:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")
