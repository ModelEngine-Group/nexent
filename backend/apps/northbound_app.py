import logging
from http import HTTPStatus
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, unquote
import re
import uuid

import httpx
from fastapi import APIRouter, Body, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr

from consts.exceptions import LimitExceededError, UnauthorizedError, ConversationNotFoundError, AdminCreateUserException
from consts.model import ToolParamsRequest
from consts.const import SERVICE_ROLE_KEY
from services.northbound_service import (
    NorthboundContext,
    get_conversation_history,
    list_conversations,
    start_streaming_chat,
    stop_chat,
    get_agent_info_list,
    update_conversation_title,
    upload_files_for_northbound,
    admin_create_user,
)
from services.tenant_service import create_tenant
from services.user_management_service import create_token
from utils.auth_utils import validate_bearer_token, get_user_and_tenant_by_access_key

from .file_management_app import build_content_disposition_header


router = APIRouter(prefix="/nb/v1", tags=["northbound"])

__all__ = ["router", "_get_northbound_context"]


class CreateUserRequest(BaseModel):
    """Request model for creating a user via northbound API."""
    email: EmailStr
    password: str
    role: str = "USER"


class UserSpec(BaseModel):
    """Spec for a single user to create during provisioning."""
    email: EmailStr
    password: str
    role: str = "USER"


class TenantProvisionSpec(BaseModel):
    """Spec for one tenant in the provisioning request."""
    tenant_name: str
    admin_email: EmailStr
    admin_password: str
    users: List[UserSpec] = []


class ProvisionTenantRequest(BaseModel):
    """Request model for bulk tenant provisioning via internal API."""
    tenants: List[TenantProvisionSpec]


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
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
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
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


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
        examples=[{
            "agents": {
                "common_sense_qa_assistant": {
                    "tools": {
                        "analyze_text_file": {
                            "chunk_size": 4000,
                            "summary_only": True,
                            "prompt": "Please provide a concise summary of this document focusing on key facts."
                        },
                        "knowledge_base_search": {
                            "top_k": 10,
                            "rerank": True,
                            "rerank_model_name": "gte-rerank-v2",
                            "index_names": ["nexent-docs", "faq-index"]
                        }
                    }
                }
            }
        }],
    ),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)
        return await start_streaming_chat(
            ctx=ctx,
            conversation_id=conversation_id,
            agent_name=agent_name,
            query=query,
            attachments=attachments,
            meta_data=meta_data,
            tool_params=tool_params,
            model_id=model_id,
            idempotency_key=idempotency_key,
        )
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except ValueError as e:
        logging.error(f"Invalid northbound chat request: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        logging.error(f"Permission denied while running northbound chat: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(e))
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
    except ConversationNotFoundError as e:
        logging.error(f"Conversation not found while updating title: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to update conversation title: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Internal Server Error")


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

    NOTE: No authentication required for this endpoint.
    """
    if not presigned_url:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="presigned_url is required"
        )

    try:
        parsed = urlparse(presigned_url)
        if parsed.scheme not in ("http", "https"):
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Invalid URL scheme. Must be http or https"
            )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Invalid presigned_url format: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Invalid presigned_url format"
        )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.get(presigned_url)

        if response.status_code != 200:
            logging.error(f"Failed to fetch file from presigned_url, status: {response.status_code}")
            raise HTTPException(
                status_code=HTTPStatus.BAD_GATEWAY,
                detail=f"Failed to fetch file from storage, status: {response.status_code}"
            )

        content_type = response.headers.get("Content-Type", "application/octet-stream")
        content_disposition = response.headers.get("Content-Disposition", "")
        download_filename = _resolve_proxy_download_filename(presigned_url, content_disposition)

        headers = {
            "Content-Type": content_type,
            "Content-Disposition": build_content_disposition_header(download_filename),
        }

        return StreamingResponse(
            content=response.aiter_bytes(),
            status_code=HTTPStatus.OK,
            headers=headers,
            media_type=content_type
        )

    except httpx.TimeoutException:
        logging.error(f"Timeout fetching file from presigned_url")
        raise HTTPException(
            status_code=HTTPStatus.GATEWAY_TIMEOUT,
            detail="Timeout fetching file from storage"
        )
    except httpx.RequestError as e:
        logging.error(f"Request error fetching file from presigned_url: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_GATEWAY,
            detail=f"Failed to fetch file from storage: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error fetching file: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


# ==================== User Management ====================

@router.post("/users")
async def create_user(
    request: Request,
    payload: CreateUserRequest,
):
    """
    Create a user for the tenant associated with the access key.

    This endpoint allows batch user creation via northbound API using
    the partner's access key for authentication.

    Args:
        request: FastAPI request object
        payload: User creation request containing email, password, and role

    Returns:
        JSONResponse with created user information
    """
    try:
        ctx: NorthboundContext = await _get_northbound_context(request)

        logging.info(
            f"Northbound user creation: email={payload.email}, "
            f"role={payload.role}, tenant_id={ctx.tenant_id}, "
            f"by user={ctx.user_id}"
        )

        user_data = await admin_create_user(
            email=payload.email,
            password=payload.password,
            role=payload.role,
            tenant_id=ctx.tenant_id
        )

        logging.info(f"Successfully created user {payload.email} in tenant {ctx.tenant_id}")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "User created successfully",
                "data": user_data
            }
        )

    except AdminCreateUserException as exc:
        error_msg = str(exc)
        if "EMAIL_ALREADY_EXISTS" in error_msg:
            logging.warning(f"User creation failed: email already exists")
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail="EMAIL_ALREADY_EXISTS"
            )
        logging.error(f"Admin create user failed: {error_msg}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=error_msg
        )
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS,
                            detail="Too Many Requests: rate limit exceeded")
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to create user: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


# ==================== Internal Provisioning ====================

@router.post("/internal/provision")
async def provision_tenant_internal(
    payload: ProvisionTenantRequest,
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    """
    Provision one or more tenants with admin users and optional members.

    Authentication: X-Internal-Key header must match SERVICE_ROLE_KEY configured
    on the server side. This endpoint is intended for offline scripts and
    provisioning tools only.

    Args:
        payload: List of tenant specs to provision

    Returns:
        JSONResponse with per-tenant results including admin access keys
    """
    # Authenticate using X-Internal-Key header
    if not SERVICE_ROLE_KEY:
        logging.error("SERVICE_ROLE_KEY not configured on server")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Internal provisioning not configured"
        )

    if x_internal_key != SERVICE_ROLE_KEY:
        logging.warning("Invalid X-Internal-Key provided for provisioning")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="Invalid internal key"
        )

    if not payload.tenants:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="At least one tenant spec is required"
        )

    results = []
    for spec in payload.tenants:
        tenant_result = await _provision_single_tenant(spec)
        results.append(tenant_result)

    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "message": f"Provisioned {len(results)} tenant(s)",
            "data": results,
        }
    )


async def _provision_single_tenant(spec: TenantProvisionSpec) -> Dict[str, Any]:
    """Create one tenant with admin user + optional members. All DB writes go through service layer."""
    try:
        tenant_info = create_tenant(
            tenant_name=spec.tenant_name,
            created_by="system-provision",
        )
    except Exception as exc:
        logging.error(f"Tenant creation failed: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Failed to create tenant: {str(exc)}"
        )

    tenant_id = tenant_info["tenant_id"]
    default_group_id = tenant_info.get("default_group_id")

    # Create admin user
    try:
        admin_info = await admin_create_user(
            email=spec.admin_email,
            password=spec.admin_password,
            role="ADMIN",
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logging.error(f"Admin creation failed: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Failed to create admin user: {str(exc)}"
        )
    admin_user_id = admin_info["user_id"]

    # Generate Access Key for admin
    try:
        token_info = create_token(admin_user_id)
        access_key = token_info["access_key"]
    except Exception as exc:
        logging.error(f"Token creation failed: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate access key: {str(exc)}"
        )

    user_results = []
    for user_spec in spec.users:
        try:
            user_info = await admin_create_user(
                email=user_spec.email,
                password=user_spec.password,
                role=user_spec.role,
                tenant_id=tenant_id,
            )
            user_results.append({
                "user_id": user_info["user_id"],
                "email": user_spec.email,
                "role": user_spec.role,
                "status": "created",
            })
        except AdminCreateUserException as exc:
            error_msg = str(exc)
            if "EMAIL_ALREADY_EXISTS" in error_msg:
                user_results.append({
                    "email": user_spec.email,
                    "role": user_spec.role,
                    "status": "skipped",
                    "reason": "email already exists",
                })
            else:
                user_results.append({
                    "email": user_spec.email,
                    "role": user_spec.role,
                    "status": "failed",
                    "reason": error_msg,
                })

    return {
        "tenant_id": tenant_id,
        "tenant_name": spec.tenant_name,
        "default_group_id": default_group_id,
        "admin": {
            "user_id": admin_user_id,
            "email": spec.admin_email,
            "access_key": access_key,
        },
        "users": user_results,
    }

