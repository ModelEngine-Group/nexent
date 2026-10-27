# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound chat, knowledge and A2A HTTP routes."""

import base64
import hashlib
import json
import logging
import re
from http import HTTPStatus
from typing import Annotated, Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

import httpx
from contracts.constants.environment import MINIO_ENDPOINT
from contracts.a2a import JSONRPCRequest
from contracts.agent import reject_legacy_agent_fields
from contracts.authentication import NorthboundContext
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.constants.constants import RATE_LIMIT_EXCEEDED_DETAIL
from contracts.knowledge import VectorDatabaseType
from contracts.constants.constants import NORTHBOUND_SERVICE_NAME
from contracts.conversation import GenerateTitleRequest
from contracts.errors.exceptions import (
    AppException,
    ConversationNotFoundError,
    ForbiddenError,
    LimitExceededError,
    NotFoundException,
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    RuntimeUpstreamError,
    TenantResourceLimitError,
    UnauthorizedError,
    ValidationError,
    tenant_resource_limit_error_payload,
)
from contracts.identity import ApiKeyTargetRequest, ApiUserBatchCreateRequest
from contracts.knowledge import HybridSearchRequest, ProcessParams
from contracts.tool import ToolParamsRequest
from fastapi import (
    APIRouter,
    Body,
    File,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
)
from fastapi import Path as PathParam
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from gateway.authentication.auth import generate_session_jwt, get_user_language
from gateway.authentication.northbound_auth import get_northbound_context as _get_northbound_context
from management.db.identity.user_tenant import get_user_role_by_tenant
from management.db.knowledge_base.repository import get_index_name_by_knowledge_name
from management.services.agent.a2a.service import (
    A2AServerServiceError,
    AgentNotEnabledError,
    EndpointNotFoundError,
    TaskNotFoundError,
    UnsupportedOperationError,
    a2a_server_service,
)
from management.services.file.service import (
    check_file_access,
    get_file_stream_impl,
    get_file_url_impl,
    upload_files_impl,
)
from management.services.knowledge_base.ingestion import trigger_data_process
from management.services.knowledge_base.service import (
    ElasticSearchService,
    KnowledgeBaseNeedsModelConfigError,
    get_vector_db_core,
)
from management.services.knowledge_base.task_state import get_redis_service
from management.services.monitor.audit import record_security_event
from management.services.permission.api_keys import (
    create_api_users_batch,
    refresh_user_api_key,
    revoke_user_api_keys,
)
from management.utils.file_http import build_content_disposition_header, build_storage_proxy_url
from pydantic import ValidationError as PydanticValidationError
from services.northbound_service import (
    generate_conversation_title,
    get_agent_info_by_name_for_northbound,
    get_agent_info_list,
    get_agent_knowledge_bases_for_northbound,
    get_conversation_history,
    list_configured_models,
    list_conversations,
    start_streaming_chat,
    stop_chat,
    update_conversation_title,
    upload_files_for_northbound,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nb/v1", tags=["northbound"])

__all__ = ["router", "_get_northbound_context"]


def _resolve_proxy_download_filename(presigned_url: str, content_disposition: str) -> str:
    """Resolve a stable download filename for the northbound file proxy."""
    if content_disposition:
        filename_star_match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition)
        if filename_star_match:
            return unquote(filename_star_match.group(1)) or "download"

        filename_match = re.search(r'filename="?([^";]+)"?', content_disposition)
        if filename_match:
            return filename_match.group(1) or "download"

    path = unquote(urlparse(presigned_url).path)
    filename = path.split("/")[-1].strip()
    return filename or "download"




@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "northbound-api"}


def _role_for_context(user_id: str, tenant_id: str) -> str:
    return get_user_role_by_tenant(user_id, tenant_id).upper()


def _raise_api_key_http_exception(exc: Exception) -> None:
    if isinstance(exc, ForbiddenError):
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc))
    if isinstance(exc, NotFoundException):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    if isinstance(exc, (PydanticValidationError, ValidationError, ValueError)):
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    raise exc


def _audit_safe_target(result: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    """Pick non-secret target fields for the audit trail.

    The service results carry the freshly created plaintext API key; only the
    whitelisted identifiers below are handed to the audit entry.
    """
    return {
        "target_user_id": (result or {}).get("user_id"),
        "target_email": (result or {}).get("email"),
        "revoked_count": (result or {}).get("revoked_count"),
        "request_id": request_id,
    }


def _audit_safe_batch(
    payload: ApiUserBatchCreateRequest,
    created: List[Dict[str, Any]],
    request_id: str,
) -> Dict[str, Any]:
    """Pick non-secret batch fields for the audit trail.

    Each created item carries a plaintext API key, so only the request intent
    and the created user ids (bounded) are recorded.
    """
    created = created or []
    return {
        "role": payload.role,
        "group_id": payload.group_id,
        "count": len(created),
        "user_ids": [item.get("user_id") for item in created][:20],
        "request_id": request_id,
    }


@router.post(
    "/api-users/batch",
    status_code=HTTPStatus.CREATED,
    tags=["northbound-api-keys"],
)
async def create_api_users_batch_endpoint(
    payload: ApiUserBatchCreateRequest,
    request: Request,
) -> JSONResponse:
    ctx = await _get_northbound_context(request)
    try:
        data = create_api_users_batch(
            actor_user_id=ctx.user_id,
            actor_tenant_id=ctx.tenant_id,
            actor_role=_role_for_context(ctx.user_id, ctx.tenant_id),
            role=payload.role,
            group_id=payload.group_id,
            count=payload.count,
        )
        record_security_event(
            "northbound_api_users_batch_create",
            request=request,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            details=_audit_safe_batch(payload, data, ctx.request_id),
        )
        return JSONResponse(
            status_code=HTTPStatus.CREATED,
            content={"message": "success", "requestId": ctx.request_id, "data": data},
        )
    except Exception as exc:
        if isinstance(exc, TenantResourceLimitError):
            return JSONResponse(
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
                content=tenant_resource_limit_error_payload(exc),
            )
        _raise_api_key_http_exception(exc)


@router.post("/api-keys/refresh", tags=["northbound-api-keys"])
async def refresh_api_key_endpoint(payload: ApiKeyTargetRequest, request: Request) -> JSONResponse:
    ctx = await _get_northbound_context(request)
    try:
        data = refresh_user_api_key(
            actor_user_id=ctx.user_id,
            actor_tenant_id=ctx.tenant_id,
            actor_role=_role_for_context(ctx.user_id, ctx.tenant_id),
            user_id=payload.user_id,
            email=str(payload.email) if payload.email else None,
        )
        record_security_event(
            "northbound_api_key_refresh",
            request=request,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            details=_audit_safe_target(data, ctx.request_id),
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "success", "requestId": ctx.request_id, "data": data},
        )
    except Exception as exc:
        _raise_api_key_http_exception(exc)


@router.delete("/api-keys", tags=["northbound-api-keys"])
async def revoke_api_key_endpoint(
    request: Request,
    user_id: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
) -> JSONResponse:
    ctx = await _get_northbound_context(request)
    try:
        target = ApiKeyTargetRequest(user_id=user_id, email=email)
        data = revoke_user_api_keys(
            actor_user_id=ctx.user_id,
            actor_tenant_id=ctx.tenant_id,
            actor_role=_role_for_context(ctx.user_id, ctx.tenant_id),
            user_id=target.user_id,
            email=str(target.email) if target.email else None,
        )
        record_security_event(
            "northbound_api_key_revoke",
            request=request,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            details=_audit_safe_target(data, ctx.request_id),
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "success", "requestId": ctx.request_id, "data": data},
        )
    except Exception as exc:
        _raise_api_key_http_exception(exc)


@router.post(
    "/chat/attachments/upload",
    summary="Upload chat attachments for northbound runs",
    description=(
        "Upload one or more files for later use in `/nb/v1/chat/run`. "
        "Successful uploads return reusable `s3_url` references."
    ),
)
async def upload_chat_attachments(
    request: Request,
    files: list[UploadFile] = File(
        ...,
        description="List of files to upload",
        examples=["report.pdf", "diagram.png"],
    ),
):
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=await upload_files_for_northbound(ctx=ctx, files=files),
        )
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail="Too Many Requests: rate limit exceeded")
    except ValueError as e:
        logging.error(f"Invalid northbound upload request: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        logging.error(f"Permission denied while uploading northbound files: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(e))
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to upload northbound files: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.post(
    "/chat/run",
    summary="Start a northbound chat run with optional attachments",
    description=(
        "Run a northbound chat request. Upload attachments first through "
        "`/nb/v1/chat/attachments/upload`, then pass the returned `s3_url` values "
        "through the `attachments` field."
    ),
)
async def run_chat(
    request: Request,
    conversation_id: Optional[int] = Body(
        None,
        embed=True,
        description="Existing conversation ID. Omit to create a new conversation.",
        examples=[123],
    ),
    agent_name: str = Body(
        ...,
        embed=True,
        description="Target agent name.",
        examples=["general-assistant"],
    ),
    query: str = Body(
        ...,
        embed=True,
        description="User input to send to the agent.",
        examples=["Summarize the uploaded report and list the key risks."],
    ),
    attachments: Optional[list] = Body(
        None,
        embed=True,
        description="Attachments for the chat. Can be either a list of S3 URL strings"
        "or a list of attachment objects with full metadata.",
        examples=[["s3://nexent/attachments/user123/20260609_report.pdf"]],
    ),
    model_id: Optional[int] = Body(
        None,
        embed=True,
        description="Optional model ID to use for this run. Overrides the agent's default "
        "model so different models can be used for Q&A on the same agent.",
        examples=[123],
    ),
    metadata: Optional[Dict[str, Any]] = Body(
        None,
        embed=True,
        description="Optional runtime metadata available to the agent. This is separate from meta_data.",
        examples=[{"project_id": "P001", "manager": "Alice"}],
    ),
    meta_data: Optional[Dict[str, Any]] = Body(
        None,
        embed=True,
        description="Optional metadata passed through for audit and usage logging.",
        examples=[{"source": "crm", "ticket_id": "INC-1001"}],
    ),
    tool_params: Optional[ToolParamsRequest] = Body(
        None,
        embed=True,
        description="Optional request-scoped overrides for tool initialization parameters. "
        "Overrides DB-persisted params (ag_tool_instance_t.params) on a per-run basis. "
        "Conflict resolution: request value wins over DB value. "
        "Structure: agents -> {agent_name} -> tools -> {tool_name} -> {param_name: param_value}. "
        "tool_name matching: first by tool.name, then by tool.class_name. "
        "Unknown param names cause a ValidationError (400). "
        "Metadata-derived fields (e.g., vdb_core, embedding_model) are recalculated "
        "from merged params for tools like KnowledgeBaseSearchTool, DifySearchTool, DataMateSearchTool.",
        examples=[
            {
                "agents": {
                    "common_sense_qa_assistant": {
                        "tools": {
                            "analyze_text_file": {
                                "chunk_size": 4000,
                                "summary_only": True,
                                "prompt": "Please provide a concise summary of this document focusing on key facts.",
                            },
                            "knowledge_base_search": {
                                "top_k": 10,
                                "rerank": True,
                                "rerank_model_name": "gte-rerank-v2",
                                "index_names": ["nexent-docs", "faq-index"],
                            },
                        }
                    }
                }
            }
        ],
    ),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    try:
        reject_legacy_agent_fields(await request.json())
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await start_streaming_chat(
            ctx=ctx,
            conversation_id=conversation_id,
            agent_name=agent_name,
            query=query,
            attachments=attachments,
            metadata=metadata,
            meta_data=meta_data,
            tool_params=tool_params,
            model_id=model_id,
            idempotency_key=idempotency_key,
        )
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail="Too Many Requests: rate limit exceeded")
    except ValueError as e:
        logging.error(f"Invalid northbound chat request: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        logging.error(f"Permission denied while running northbound chat: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(e))
    except RuntimeServiceTimeoutError as e:
        raise HTTPException(status_code=HTTPStatus.GATEWAY_TIMEOUT, detail=str(e)) from e
    except RuntimeServiceUnavailableError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_GATEWAY, detail=str(e)) from e
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to run chat: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


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
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail="Too Many Requests: rate limit exceeded")
    except RuntimeUpstreamError as e:
        return Response(
            content=e.content,
            status_code=e.status_code,
            headers=e.headers,
        )
    except RuntimeServiceTimeoutError as e:
        raise HTTPException(status_code=HTTPStatus.GATEWAY_TIMEOUT, detail=str(e)) from e
    except RuntimeServiceUnavailableError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_GATEWAY, detail=str(e)) from e
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to stop chat: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


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
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail="Too Many Requests: rate limit exceeded")
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to get conversation history: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/agents")
async def list_agents(request: Request):
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await get_agent_info_list(ctx=ctx)
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail="Too Many Requests: rate limit exceeded")
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to list agents: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/agents/{agent_name}")
async def get_agent_by_name(
    request: Request,
    agent_name: str,
):
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await get_agent_info_by_name_for_northbound(ctx=ctx, agent_name=agent_name)
    except ValueError as e:
        logging.error(f"Invalid agent detail request: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except LookupError as e:
        logging.info(f"Published agent not found: {agent_name}")
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail="Too Many Requests: rate limit exceeded")
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to get agent by name: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/agents/{agent_name}/knowledge-bases")
async def get_agent_knowledge_bases(
    request: Request,
    agent_name: str,
):
    """List knowledge bases the current northbound caller may use with an agent."""
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await get_agent_knowledge_bases_for_northbound(ctx, agent_name)
    except ValueError as exc:
        status = HTTPStatus.CONFLICT if "both local and AIDP" in str(exc) else HTTPStatus.BAD_REQUEST
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from exc
    except LimitExceededError as exc:
        raise HTTPException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            detail="Too Many Requests: rate limit exceeded",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logging.error(
            "Failed to list northbound agent knowledge bases: %s",
            exc,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Internal Server Error",
        ) from exc


@router.get("/conversations")
async def list_convs(request: Request):
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await list_conversations(ctx=ctx)
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail="Too Many Requests: rate limit exceeded")
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to list conversations: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/models")
async def list_models(request: Request):
    """List the models configured for the authenticated tenant."""
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await list_configured_models(ctx=ctx)
    except HTTPException:
        raise
    except Exception as exc:
        logging.error("Failed to list configured models: %s", exc, exc_info=exc)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Internal Server Error",
        ) from exc


@router.post("/generate_title")
async def generate_title(payload: GenerateTitleRequest, request: Request):
    """Generate and persist a conversation title from the supplied question."""
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await generate_conversation_title(
            ctx=ctx,
            conversation_id=payload.conversation_id,
            question=payload.question,
            language=get_user_language(request),
            model_id=payload.model_id,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logging.error("Failed to generate conversation title: %s", exc, exc_info=exc)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Internal Server Error",
        ) from exc


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
        headers_out = {"Idempotency-Key": result.get("idempotency_key", ""), "X-Request-Id": ctx.request_id}
        return JSONResponse(content=result, headers=headers_out)

    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail="Too Many Requests: rate limit exceeded")
    except ConversationNotFoundError as e:
        logging.error(f"Conversation not found while updating title: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to update conversation title: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


@router.get("/file/fetch")
async def fetch_file_from_presigned_url(
    presigned_url: str = Query(..., description="Presigned URL from MinIO storage"),
):
    """
    Fetch file content from a MinIO presigned URL.

    This endpoint acts as a proxy - it downloads the file from MinIO
    (which is only accessible from within the container network) and
    returns the file content to external callers (e.g., MCP tools).

    The presigned_url parameter should be URL-encoded by the caller.

    No separate login is required; MinIO verifies the signed URL. Only the
    configured storage origin is permitted, and redirects are never followed.
    """
    if not presigned_url:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="presigned_url is required")

    storage_url = build_storage_proxy_url(presigned_url, MINIO_ENDPOINT)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=False, trust_env=False) as client:
            response = await client.get(storage_url)

        if response.status_code != 200:
            logging.error(f"Failed to fetch file from presigned_url, status: {response.status_code}")
            raise HTTPException(
                status_code=HTTPStatus.BAD_GATEWAY,
                detail=f"Failed to fetch file from storage, status: {response.status_code}",
            )

        content_type = response.headers.get("Content-Type", "application/octet-stream")
        content_disposition = response.headers.get("Content-Disposition", "")
        download_filename = _resolve_proxy_download_filename(presigned_url, content_disposition)

        headers = {
            "Content-Type": content_type,
            "Content-Disposition": build_content_disposition_header(download_filename),
        }

        return StreamingResponse(
            content=response.aiter_bytes(), status_code=HTTPStatus.OK, headers=headers, media_type=content_type
        )

    except httpx.TimeoutException:
        logging.error(f"Timeout fetching file from presigned_url")
        raise HTTPException(status_code=HTTPStatus.GATEWAY_TIMEOUT, detail="Timeout fetching file from storage")
    except httpx.RequestError:
        logging.error("Request error fetching file from configured storage")
        raise HTTPException(status_code=HTTPStatus.BAD_GATEWAY, detail="Failed to fetch file from storage") from None
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error fetching file: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal server error")


async def _require_asset_owner_context(request: Request) -> NorthboundContext:
    """Resolve northbound context and ensure the caller belongs to the asset-owner tenant."""
    ctx = await _get_northbound_context(request)
    if ctx.tenant_id != ASSET_OWNER_TENANT_ID:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="This endpoint is restricted to asset administrators.",
        )
    return ctx


@router.get("/knowledge/indices")
async def get_list_indices(
    request: Request,
    pattern: Annotated[str, Query(description="Pattern to match index names")] = "*",
):
    """List knowledge bases visible to the asset-owner tenant.

    Restricted to asset administrators (same auth as create_new_index).
    """
    try:
        ctx = await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)
        return ElasticSearchService.list_indices(pattern, True, ctx.tenant_id, ctx.user_id, vdb_core)
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while listing knowledge bases")
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error listing knowledge bases")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error listing knowledge bases")


@router.post("/knowledge/indices/{index_name}")
async def create_new_index(
    request: Request,
    index_name: Annotated[str, Path(..., description="Name of the index to create")],
    embedding_dim: Annotated[
        Optional[int],
        Query(description="Dimension of the embedding vectors"),
    ] = None,
    body: Annotated[
        Optional[Dict[str, Any]],
        Body(
            description=("Request body containing embedding_model_id and optional knowledge-base settings"),
        ),
    ] = None,
):
    """Create a new vector index and store it in the knowledge table.

    Restricted to the asset-owner tenant: only callers whose access key resolves
    to the asset-owner tenant are allowed to create knowledge bases through the
    northbound API.
    """
    try:
        ctx = await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)

        ingroup_permission = None
        group_ids = None
        embedding_model_id = None
        preserve_source_file = None
        if body:
            ingroup_permission = body.get("ingroup_permission")
            group_ids = body.get("group_ids")
            embedding_model_id = body.get("embedding_model_id")
            preserve_source_file = body.get("preserve_source_file")

        if isinstance(embedding_model_id, bool) or not isinstance(embedding_model_id, int):
            raise ValueError("embedding_model_id must be an integer")

        return ElasticSearchService.create_knowledge_base(
            knowledge_name=index_name,
            embedding_dim=embedding_dim,
            vdb_core=vdb_core,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            ingroup_permission=ingroup_permission,
            group_ids=group_ids,
            embedding_model_id=embedding_model_id,
            preserve_source_file=preserve_source_file,
        )
    except AppException:
        # Preserve the standard error code/details for knowledge resource limits.
        raise
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while creating index")
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception:
        logger.exception("Error creating index")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error creating index")


@router.delete("/knowledge/indices/{index_name}")
async def delete_index(
    request: Request,
    index_name: Annotated[str, Path(..., description="Name of the index to delete")],
):
    """Delete a knowledge base and all related data.

    Restricted to asset administrators (same auth as create_new_index).
    """
    logger.debug("Received northbound request to delete knowledge base")
    try:
        ctx = await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)
        return await ElasticSearchService.full_delete_knowledge_base(index_name, vdb_core, ctx.user_id)
    except AppException:
        # Preserve the EDS code/details for northbound clients.
        raise
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while deleting index")
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error deleting index")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error deleting index")


@router.get("/knowledge/indices/{index_name}/files")
async def get_index_files(
    request: Request,
    index_name: Annotated[str, Path(..., description="Name of the index")],
):
    """Get all files from an index, including those that are not yet stored in ES.

    Restricted to asset administrators (same auth as get_list_indices).
    """
    try:
        ctx = await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)
        logger.debug(
            "Listing files for index %s, tenant_id=%s, user_id=%s",
            index_name,
            ctx.tenant_id,
            ctx.user_id,
        )
        result = await ElasticSearchService.list_files(index_name, include_chunks=False, vdb_core=vdb_core)
        return {
            "status": "success",
            "files": result.get("files", []),
        }
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while listing files")
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error getting files for index")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error getting index files")


@router.post("/knowledge/indices/{index_name}/chunks")
async def get_index_chunks(
    request: Request,
    index_name: Annotated[str, Path(..., description="Name of the index")],
    page: Annotated[
        Optional[int],
        Query(description="Page number (1-based) for pagination"),
    ] = None,
    page_size: Annotated[
        Optional[int],
        Query(description="Number of records per page for pagination"),
    ] = None,
    path_or_url: Annotated[
        Optional[str],
        Query(description="Filter chunks by document path_or_url"),
    ] = None,
):
    """Get chunks from the specified index, with optional pagination.

    Restricted to asset administrators (same auth as get_list_indices).
    """
    try:
        ctx = await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)

        if path_or_url is not None and not check_file_access(path_or_url, ctx.user_id, ctx.tenant_id):
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="You don't have permission to access this file",
            )

        return ElasticSearchService.get_index_chunks(
            index_name=index_name,
            page=page,
            page_size=page_size,
            path_or_url=path_or_url,
            vdb_core=vdb_core,
        )
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while getting chunks")
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error getting chunks for index")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error getting chunks")


@router.post("/knowledge/indices/search/hybrid")
async def hybrid_search(
    request: Request,
    payload: HybridSearchRequest,
):
    """Run a hybrid (accurate + semantic) search across indices.

    Restricted to asset administrators (same auth as get_list_indices).
    """
    try:
        ctx = await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)

        resolved_index_names: List[str] = []
        for requested_name in payload.index_names:
            try:
                resolved_name = get_index_name_by_knowledge_name(requested_name, ctx.tenant_id)
            except Exception:
                resolved_name = requested_name
            resolved_index_names.append(resolved_name)

        return ElasticSearchService.search_hybrid(
            index_names=resolved_index_names,
            query=payload.query,
            tenant_id=ctx.tenant_id,
            top_k=payload.top_k,
            weight_accurate=payload.weight_accurate,
            vdb_core=vdb_core,
        )
    except KnowledgeBaseNeedsModelConfigError as exc:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail={
                "error_type": "KNOWLEDGE_BASE_NEEDS_MODEL_CONFIG",
                "index_name": exc.index_name,
                "message": exc.message,
                "suggestion": ("Please select an embedding model for this knowledge base before searching."),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while running hybrid search")
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error executing hybrid search")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error executing hybrid search")


@router.delete("/knowledge/indices/{index_name}/documents")
async def delete_documents(
    request: Request,
    index_name: Annotated[str, Path(..., description="Name of the index")],
    path_or_url: Annotated[str, Query(..., description="Path or URL of documents to delete")],
    scope: Annotated[
        str,
        Query(
            description=("source_only: delete MinIO source only; full: delete ES, MinIO, and Redis records"),
        ),
    ] = "full",
):
    """Delete a document by scope. Restricted to asset administrators."""
    try:
        await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)
        logger.debug("Deleting documents for index %s scope=%s", index_name, scope)
        result = await ElasticSearchService.delete_document_by_scope(index_name, path_or_url, scope, vdb_core)

        if scope == "full":
            try:
                redis_service = get_redis_service()
                redis_cleanup_result = redis_service.delete_document_records(index_name, path_or_url)
                result["redis_cleanup"] = redis_cleanup_result
                original_message = result.get("message", "Documents deleted successfully")
                result["message"] = (
                    f"{original_message}. "
                    f"Cleaned up {redis_cleanup_result['total_deleted']} Redis records "
                    f"({redis_cleanup_result['celery_tasks_deleted']} tasks, "
                    f"{redis_cleanup_result['cache_keys_deleted']} cache keys)."
                )
                if redis_cleanup_result.get("errors"):
                    result["redis_warnings"] = redis_cleanup_result["errors"]
            except Exception as redis_error:
                logger.warning(
                    "Redis cleanup failed for index %s: %s",
                    index_name,
                    redis_error,
                )
                result["redis_cleanup_error"] = str(redis_error)
                original_message = result.get("message", "Documents deleted successfully")
                result["message"] = f"{original_message}, but Redis cleanup encountered an error: {str(redis_error)}"

        return result
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while deleting documents")
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error deleting documents for index")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error deleting documents")


@router.post("/knowledge/file/upload")
async def upload_files(
    request: Request,
    file: Annotated[List[UploadFile], File(..., alias="file")],
    index_name: str = Form(..., description="Knowledge base index"),
):
    """Upload files to MinIO and trigger knowledge base data processing.

    Uses chunking_strategy=basic. Restricted to asset administrators
    (same auth as create_new_index).
    """
    try:
        ctx = await _require_asset_owner_context(request)
        destination = "minio"
        if not file:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="No files in the request",
            )

        errors, uploaded_file_paths, uploaded_filenames = await upload_files_impl(
            destination,
            file,
            None,
            index_name,
            ctx.user_id,
            uploader_tenant_id=ctx.tenant_id,
            upload_owner_service=NORTHBOUND_SERVICE_NAME,
        )

        if uploaded_file_paths:
            files = [
                {"path_or_url": path, "filename": name} for path, name in zip(uploaded_file_paths, uploaded_filenames)
            ]
            # Internal data-process / ES indexing expects JWT, not northbound API key
            internal_jwt = generate_session_jwt(ctx.user_id)
            process_params = ProcessParams(
                chunking_strategy="basic",
                source_type="minio",
                index_name=index_name,
                authorization=internal_jwt,
            )
            process_result = await trigger_data_process(files, process_params, tenant_id=ctx.tenant_id)

            if process_result is None or (
                isinstance(process_result, dict) and process_result.get("status") == "error"
            ):
                error_message = "Data process service failed"
                if isinstance(process_result, dict) and "message" in process_result:
                    error_message = process_result["message"]
                raise HTTPException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    detail=error_message,
                )

            return JSONResponse(
                status_code=HTTPStatus.CREATED,
                content={
                    "message": ("Files uploaded and processing triggered successfully"),
                    "uploaded_filenames": uploaded_filenames,
                    "uploaded_file_paths": uploaded_file_paths,
                    "errors": errors,
                    "process_tasks": process_result,
                },
            )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="No valid files uploaded",
        )
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while uploading files")
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except AppException:
        raise
    except Exception:
        logger.exception("File upload error")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="File upload error.")


@router.get("/knowledge/file/download/{object_name:path}")
async def get_storage_file(
    request: Request,
    object_name: str = PathParam(..., description="File object name"),
    download: str = Query(
        "ignore",
        description=(
            "How to get the file: "
            "'ignore' (default, return file info), "
            "'stream' (return file stream), "
            "'redirect' (redirect to download URL), "
            "'base64' (return base64-encoded content for images)."
        ),
    ),
    expires: int = Query(86400, description="URL validity period (seconds)"),
    filename: Optional[str] = Query(None, description="Original filename for download (optional)"),
):
    """Get file information, download link, or file stream.

    Restricted to asset administrators (same auth as create_new_index).
    """
    try:
        ctx = await _require_asset_owner_context(request)

        if not check_file_access(object_name, ctx.user_id, ctx.tenant_id):
            logger.warning(
                "[get_storage_file] Access denied: user_id=%s",
                ctx.user_id,
            )
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="You don't have permission to access this file",
            )

        logger.info(
            "[get_storage_file] download=%s",
            download,
        )
        if download == "redirect":
            result = await get_file_url_impl(object_name=object_name, expires=expires)
            return RedirectResponse(url=result["url"])
        if download == "stream":
            file_stream, content_type = await get_file_stream_impl(object_name=object_name)
            logger.info(
                "Streaming file: object_name=%s, content_type=%s",
                object_name,
                content_type,
            )

            download_filename = filename
            if not download_filename:
                download_filename = object_name.split("/")[-1] if "/" in object_name else object_name

            content_disposition = build_content_disposition_header(download_filename)

            return StreamingResponse(
                file_stream,
                media_type=content_type,
                headers={
                    "Content-Disposition": content_disposition,
                    "Cache-Control": "public, max-age=3600",
                    "ETag": f'"{object_name}"',
                },
            )
        if download == "base64":
            file_stream, content_type = await get_file_stream_impl(object_name=object_name)
            try:
                data = file_stream.read()
            except Exception as exc:
                logger.error("Failed to read file stream for base64: %s", str(exc))
                raise HTTPException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    detail="Failed to read file content for base64 encoding",
                )

            base64_content = base64.b64encode(data).decode("utf-8")
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "success": True,
                    "base64": base64_content,
                    "content_type": content_type,
                    "object_name": object_name,
                },
            )
        return await get_file_url_impl(object_name=object_name, expires=expires)
    except LimitExceededError as e:
        logger.error(
            "%s: %s",
            RATE_LIMIT_EXCEEDED_DETAIL,
            str(e),
            exc_info=e,
        )
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get file")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to get file.")


# =============================================================================
# A2A Server Endpoints (Combined into northbound_base_app)
# =============================================================================

# Create separate router for A2A endpoints
a2a_router = APIRouter(prefix="/nb/a2a", tags=["Northbound A2A"])


@a2a_router.get("/{endpoint_id}/.well-known/agent-card.json")
async def get_agent_card(
    endpoint_id: str,
    request: Request,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
):
    """Get Agent Card for A2A discovery.

    Standard A2A 1.0 discovery endpoint at /nb/a2a/{endpoint_id}/.well-known/agent-card.json.
    Supports HTTP caching via ETag.
    """
    try:
        base_url = str(request.base_url).rstrip("/")

        card = a2a_server_service.get_agent_card(endpoint_id=endpoint_id, base_url=base_url, use_northbound=True)

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
            },
        )

    except EndpointNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Get agent card failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get agent card",
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
        ctx = await _get_northbound_context(request)

        if payload.method == "SendMessage":
            result = await _handle_jsonrpc_send(endpoint_id, payload.params or {}, ctx)
            return JSONResponse({"jsonrpc": "2.0", "result": result, "id": payload.id})
        elif payload.method == "SendStreamingMessage":
            return await _handle_jsonrpc_stream(endpoint_id, payload.params or {}, ctx, payload.id)
        elif payload.method == "GetTask":
            result = _handle_jsonrpc_get_task(endpoint_id, payload.params or {}, ctx)
            return JSONResponse({"jsonrpc": "2.0", "result": result, "id": payload.id})
        else:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {payload.method}",
                    },
                    "id": payload.id,
                }
            )

    except EndpointNotFoundError as e:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": "Endpoint not found"},
                "id": payload.id,
            }
        )
    except TaskNotFoundError as e:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32001, "message": "Task not found"},
                "id": payload.id,
            }
        )
    except UnsupportedOperationError as e:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32004, "message": "Unsupported operation"},
                "id": payload.id,
            }
        )
    except Exception as e:
        logger.error(f"JSON-RPC handler error for endpoint {endpoint_id}: {e}", exc_info=True)
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": "Internal error"},
                "id": payload.id,
            }
        )


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
        tenant_id=ctx.tenant_id,
    )
    return result


def _handle_jsonrpc_get_task(endpoint_id: str, params: Dict[str, Any], ctx: NorthboundContext) -> Dict[str, Any]:
    """Handle JSON-RPC GetTask method."""
    task_id = params.get("id")
    if not task_id:
        raise A2AServerServiceError("Missing required parameter: id")

    result = a2a_server_service.get_task(task_id=task_id, user_id=ctx.user_id, tenant_id=ctx.tenant_id)
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
        return {"jsonrpc": "2.0", "id": jsonrpc_id, "result": event}

    async def generate_sse():
        try:
            async for event in a2a_server_service.handle_message_stream(
                endpoint_id=endpoint_id,
                message=message,
                token_id=ctx.token_id,
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id,
            ):
                wrapped = wrap_jsonrpc(event)
                yield f"data: {json.dumps(wrapped)}\n\n"
        except Exception as e:
            logger.error(f"SSE stream error: {e}", exc_info=True)
            error_event = {
                "jsonrpc": "2.0",
                "id": jsonrpc_id,
                "error": {"code": -32603, "message": str(e)},
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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
        ctx = await _get_northbound_context(request)

        result = await a2a_server_service.handle_message_send(
            endpoint_id=endpoint_id,
            message=message,
            token_id=ctx.token_id,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
        )

        return JSONResponse(status_code=HTTPStatus.OK, content=result)

    except EndpointNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except AgentNotEnabledError as e:
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        logger.error(f"REST message send failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to send message",
        )


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
        ctx = await _get_northbound_context(request)

        async def generate_sse():
            try:
                async for event in a2a_server_service.handle_message_stream(
                    endpoint_id=endpoint_id,
                    message=message,
                    token_id=ctx.token_id,
                    user_id=ctx.user_id,
                    tenant_id=ctx.tenant_id,
                ):
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as e:
                logger.error(f"SSE stream error: {e}", exc_info=True)
                fail_payload = json.dumps(
                    {
                        "statusUpdate": {
                            "taskId": "",
                            "status": {
                                "state": "TASK_STATE_FAILED",
                                "message": "An internal error occurred while processing the stream.",
                            },
                        }
                    }
                )
                yield f"data: {fail_payload}\n\n"

        return StreamingResponse(
            generate_sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except EndpointNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except AgentNotEnabledError as e:
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        logger.error(f"REST message stream failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to stream message",
        )


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
        ctx: NorthboundContext = await _get_northbound_context(request)

        task = a2a_server_service.get_task(task_id=task_id, user_id=ctx.user_id, tenant_id=ctx.tenant_id)

        return JSONResponse({"task": task})

    except TaskNotFoundError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"REST get task failed: {e}", exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to get task")
