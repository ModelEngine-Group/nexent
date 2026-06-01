import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from os.path import basename
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile
from fastapi.responses import StreamingResponse


from consts.const import ASSET_OWNER_TENANT_ID
from consts.exceptions import (
    LimitExceededError,
    UnauthorizedError,
    ConversationNotFoundError,
)
from consts.model import AgentRequest, ToolParamsRequest
from database.conversation_db import get_conversation_messages, get_source_searches_by_message
from database.token_db import log_token_usage, get_latest_usage_metadata
from services.agent_service import (
    run_agent_stream,
    stop_agent_tasks,
    get_agent_id_by_name
)
from services.agent_version_service import list_published_agents_impl
from services.conversation_management_service import (
    save_conversation_user,
    get_conversation_list_service,
    create_new_conversation,
    update_conversation_title as update_conversation_title_service,
)
from services.file_management_service import upload_to_minio, resolve_minio_upload_folder, validate_urls_access
from database.attachment_db import get_file_url, get_file_size_from_minio
from nexent.multi_modal.utils import parse_s3_url

logger = logging.getLogger("northbound_service")


@dataclass
class NorthboundContext:
    request_id: str
    tenant_id: str
    user_id: str
    authorization: str
    token_id: int = 0


def _build_northbound_file_descriptor(
    upload_result: Dict[str, Any],
    original_file_name: str = "",
    file_type: Optional[str] = None,
    file_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Normalize upload metadata for northbound API consumers."""
    object_name = str(upload_result.get("object_name") or "").strip()
    # Use original filename if provided, otherwise fall back to upload result or object name
    if original_file_name:
        file_name = original_file_name
    else:
        file_name = str(upload_result.get("file_name") or basename(object_name) or "")
    # Frontend-compatible field order
    descriptor = {
        "object_name": object_name,
        "name": file_name,
        "type": file_type or "file",
        # Use provided file_size, or from upload_result, or 0 as fallback
        "size": file_size if file_size is not None else upload_result.get("file_size", 0),
        # Use relative URL format matching frontend: /nexent/{object_name}
        "url": f"/nexent/{object_name}",
        "description": "",
    }
    presigned_url = upload_result.get("presigned_url")
    if presigned_url:
        descriptor["presigned_url"] = presigned_url
    return descriptor


async def upload_files_for_northbound(
    ctx: NorthboundContext,
    files: List[UploadFile],
    folder: str = "attachments",
) -> Dict[str, Any]:
    """Upload files for northbound callers and return reusable storage references."""
    if not files:
        raise ValueError("No files in the request")

    actual_folder = resolve_minio_upload_folder(folder, ctx.user_id, ctx.tenant_id)
    results = await upload_to_minio(files=files, folder=actual_folder)
    normalized_files = []
    for result, upload_file in zip(results, files):
        if result.get("success") and result.get("object_name"):
            content_type = result.get("content_type", "")
            file_type = "image" if content_type.startswith("image/") else "file"
            # Extract original filename - use upload result first, then fallback to UploadFile
            # The upload result contains the original filename passed to upload_fileobj
            original_file_name = result.get("original_file_name") or upload_file.filename or ""
            file_size = result.get("file_size", 0)
            # If file_size is 0 but we have the UploadFile, try to get size from headers
            if file_size == 0 and hasattr(upload_file, 'size') and upload_file.size:
                file_size = upload_file.size
            descriptor = _build_northbound_file_descriptor(
                result,
                original_file_name=original_file_name,
                file_type=file_type,
                file_size=file_size,
            )
            normalized_files.append(descriptor)

    if not normalized_files:
        raise ValueError("No valid files uploaded")

    success_count = sum(1 for result in results if result.get("success", False))
    failed_count = sum(1 for result in results if not result.get("success", False))

    return {
        "message": f"Processed {len(results)} files",
        "requestId": ctx.request_id,
        "summary": {
            "total": len(results),
            "uploaded": success_count,
            "failed": failed_count,
        },
        "files": normalized_files,
    }


def _normalize_northbound_attachments(
    attachments: Optional[List[Any]],
    user_id: str,
    tenant_id: str,
) -> Optional[List[Dict[str, Any]]]:
    """Convert northbound attachment references into internal minio_files objects.

    Supports two formats:
    1. List of S3 URL strings (backward compatible): ["s3://nexent/...", "/nexent/...", "attachments/..."]
    2. List of attachment objects (full metadata): [{"object_name": "...", "name": "...", ...}]
    """
    from database.attachment_db import _build_mcp_presigned_url

    if attachments is None:
        return None
    if not isinstance(attachments, list):
        raise ValueError("attachments must be an array")

    normalized_files: List[Dict[str, Any]] = []
    for attachment in attachments:
        # Handle dict format (full attachment object)
        if isinstance(attachment, dict):
            # Use the attachment dict directly, just ensure required fields
            normalized_file = {
                "object_name": attachment.get("object_name", ""),
                "name": attachment.get("name", basename(attachment.get("object_name", ""))),
                "type": attachment.get("type", "file"),
                "size": attachment.get("size", 0),
                "url": attachment.get("url", ""),
                "description": attachment.get("description", ""),
            }
            # Add presigned_url if available, or generate one if we have object_name
            if "presigned_url" in attachment:
                normalized_file["presigned_url"] = attachment["presigned_url"]
            elif normalized_file.get("object_name"):
                try:
                    presigned_result = get_file_url(object_name=normalized_file["object_name"], expires=86400)
                    if presigned_result.get("success") and presigned_result.get("url"):
                        normalized_file["presigned_url"] = _build_mcp_presigned_url(presigned_result["url"])
                except Exception:
                    pass
            normalized_files.append(normalized_file)
            continue

        # Handle string format (S3 URL)
        if not isinstance(attachment, str) or not attachment.strip():
            raise ValueError("attachments must contain non-empty S3 URLs or object paths")

        attachment_url = attachment.strip()

        # Support multiple URL formats:
        # 1. s3://nexent/attachments/xxx.md
        # 2. /nexent/attachments/xxx.md
        # 3. attachments/xxx.md (relative path)
        if attachment_url.startswith("s3://"):
            try:
                _, object_name = parse_s3_url(attachment_url)
            except ValueError as exc:
                raise ValueError(f"Invalid S3 URL format: {attachment_url}") from exc
            validate_url = attachment_url
        elif attachment_url.startswith("/nexent/"):
            object_name = attachment_url[len("/nexent/"):]
            validate_url = f"s3://nexent/{object_name}"
        elif attachment_url.startswith("attachments/") or attachment_url.startswith("nexent/"):
            object_name = attachment_url if attachment_url.startswith("nexent/") else attachment_url
            validate_url = f"s3://nexent/{object_name}"
        else:
            raise ValueError(f"Invalid attachment format: {attachment_url}. Expected s3:// URL, /nexent/ path, or attachments/ path")

        try:
            validate_urls_access([validate_url], user_id, tenant_id)
            presigned_result = get_file_url(object_name=object_name, expires=86400)
        except PermissionError as exc:
            detail = str(exc)
            if "Invalid S3 URL format" in detail:
                raise ValueError(detail) from exc
            raise PermissionError(detail) from exc

        # Get file size from MinIO
        try:
            file_size = get_file_size_from_minio(object_name)
        except Exception:
            file_size = 0

        # Build frontend-compatible minio_files format
        file_name = basename(object_name.rstrip("/"))
        normalized_file = {
            "object_name": object_name,
            "name": file_name,
            "type": "file",
            "size": file_size,
            # Use relative URL format matching frontend: /nexent/{object_name}
            "url": f"/nexent/{object_name}",
            "description": "",
        }
        # Use MCP proxy URL for presigned_url (same as frontend format)
        if presigned_result.get("success") and presigned_result.get("url"):
            normalized_file["presigned_url"] = _build_mcp_presigned_url(presigned_result["url"])
        normalized_files.append(normalized_file)

    return normalized_files


# -----------------------------
# In-memory idempotency and rate limit placeholders
# -----------------------------
_IDEMPOTENCY_RUNNING: Dict[str, float] = {}
_IDEMPOTENCY_TTL_SECONDS_DEFAULT = 10 * 60
_IDEMPOTENCY_LOCK = asyncio.Lock()

_RATE_LIMIT_PER_MINUTE = 120  # simple default quota per tenant per minute
_RATE_STATE: Dict[str, Dict[str, int]] = {}
_RATE_LOCK = asyncio.Lock()


def _now_seconds() -> float:
    return time.time()


def _minute_bucket(ts: Optional[float] = None) -> str:
    t = int((ts or _now_seconds()) // 60)
    return str(t)


async def idempotency_start(key: str, ttl_seconds: Optional[int] = None) -> None:
    async with _IDEMPOTENCY_LOCK:
        # purge expired
        now = _now_seconds()
        expired = [k for k, v in _IDEMPOTENCY_RUNNING.items() if now - v > (ttl_seconds or _IDEMPOTENCY_TTL_SECONDS_DEFAULT)]
        for k in expired:
            _IDEMPOTENCY_RUNNING.pop(k, None)
        if key in _IDEMPOTENCY_RUNNING:
            raise LimitExceededError("Duplicate request is still running, please wait.")
        _IDEMPOTENCY_RUNNING[key] = now


async def idempotency_end(key: str) -> None:
    async with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY_RUNNING.pop(key, None)


async def _release_idempotency_after_delay(key: str, seconds: int = 3) -> None:
    await asyncio.sleep(seconds)
    await idempotency_end(key)


async def check_and_consume_rate_limit(tenant_id: str) -> None:
    bucket = _minute_bucket()
    async with _RATE_LOCK:
        state = _RATE_STATE.setdefault(tenant_id, {})
        count = state.get(bucket, 0)
        if count >= _RATE_LIMIT_PER_MINUTE:
            raise LimitExceededError("Query rate exceeded limit. Please try again later")
        state[bucket] = count + 1
        # cleanup old buckets, keep only current
        for b in list(state.keys()):
            if b != bucket:
                state.pop(b, None)


def _build_idempotency_key(*parts: Any) -> str:
    """Compose a generic idempotency key from arbitrary parts.

    Long text components (\u003e64 chars) are replaced with their SHA256 hash to avoid extremely long keys.
    """
    processed = []
    for p in parts:
        s = "" if p is None else str(p)
        # Hash very long segments to keep key length reasonable
        if len(s) > 64:
            s = hashlib.sha256(s.encode("utf-8")).hexdigest()
        processed.append(s)
    return ":".join(processed)


def _build_title_update_idempotency_key(tenant_id: str, conversation_id: int, title: str) -> str:
    """Build an ASCII-safe idempotency key for title updates."""
    title_hash = hashlib.sha256(title.encode("utf-8")).hexdigest()
    return _build_idempotency_key(tenant_id, str(conversation_id), title_hash)


# -----------------------------
# Agent resolver
# -----------------------------
async def get_agent_info_by_name(agent_name: str, tenant_id: str) -> int:
    try:
        return await get_agent_id_by_name(agent_name=agent_name, tenant_id=tenant_id)
    except Exception as _:
        raise Exception(f"Failed to get agent id for agent_name: {agent_name} in tenant_id: {tenant_id}")


async def start_streaming_chat(
    ctx: NorthboundContext,
    conversation_id: Optional[int],
    agent_name: str,
    query: str,
    attachments: Optional[List[Any]] = None,
    meta_data: Optional[Dict[str, Any]] = None,
    tool_params: Optional[ToolParamsRequest] = None,
    model_id: Optional[int] = None,
    idempotency_key: Optional[str] = None
) -> StreamingResponse:
    try:
        # Simple rate limit
        await check_and_consume_rate_limit(ctx.tenant_id)

        # If conversation_id is not provided, create a new conversation
        if conversation_id is None:
            logging.info("No conversation_id provided, creating a new conversation")
            new_conversation = create_new_conversation(title="New Conversation", user_id=ctx.user_id)
            conversation_id = new_conversation["conversation_id"]
            logging.info(f"Created new conversation with id: {conversation_id}")

        internal_conversation_id = conversation_id

        # Get history according to internal_conversation_id
        history_resp = await get_conversation_history_internal(ctx, internal_conversation_id)
        agent_id = await get_agent_id_by_name(agent_name=agent_name, tenant_id=ctx.tenant_id)
        normalized_attachments = _normalize_northbound_attachments(
            attachments=attachments,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
        )
        # Idempotency: only prevent concurrent duplicate starts
        composed_key = idempotency_key or _build_idempotency_key(ctx.tenant_id, str(conversation_id), agent_id, query)
        await idempotency_start(composed_key)
        agent_request = AgentRequest(
            conversation_id=internal_conversation_id,
            agent_id=agent_id,
            query=query,
            history=(history_resp.get("data", {})).get("history", []),
            minio_files=normalized_attachments,
            is_debug=False,
            tool_params=tool_params,
            model_id=model_id,
        )

        # Synchronously persist the user message before starting the stream to avoid race conditions
        try:
            save_conversation_user(
                agent_request, user_id=ctx.user_id, tenant_id=ctx.tenant_id)
        except Exception as e:
            raise Exception(f"Failed to persist user message: {str(e)}")

    except LimitExceededError as _:
        raise LimitExceededError("Query rate exceeded limit. Please try again later.")
    except UnauthorizedError as _:
        raise UnauthorizedError("Cannot authenticate.")
    except Exception as e:
        raise Exception(f"Failed to start streaming chat for conversation_id {conversation_id}: {str(e)}")

    try:
        response = await run_agent_stream(
            agent_request=agent_request,
            http_request=None,
            authorization=ctx.authorization,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            skip_user_save=True,
        )
    finally:
        if composed_key:
            asyncio.create_task(_release_idempotency_after_delay(composed_key))

    # Log token usage
    if ctx.token_id > 0:
        try:
            log_token_usage(
                token_id=ctx.token_id,
                call_function_name="run_chat",
                related_id=conversation_id,
                created_by=ctx.user_id,
                metadata=meta_data
            )
        except Exception as e:
            logger.warning(f"Failed to log token usage: {str(e)}")

    # Attach request id header and conversation_id (internal id)
    response.headers["X-Request-Id"] = ctx.request_id
    response.headers["conversation_id"] = str(conversation_id)
    return response


async def stop_chat(ctx: NorthboundContext, conversation_id: int, meta_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        stop_result = stop_agent_tasks(conversation_id, ctx.user_id)

        # Log token usage
        if ctx.token_id > 0:
            try:
                log_token_usage(
                    token_id=ctx.token_id,
                    call_function_name="stop_chat_stream",
                    related_id=conversation_id,
                    created_by=ctx.user_id,
                    metadata=meta_data
                )
            except Exception as e:
                logger.warning(f"Failed to log token usage: {str(e)}")

        return {"message": stop_result.get("message", "success"), "data": conversation_id, "requestId": ctx.request_id}
    except Exception as e:
        raise Exception(f"Failed to stop chat for conversation_id {conversation_id}: {str(e)}")


async def list_conversations(ctx: NorthboundContext) -> Dict[str, Any]:
    conversations = get_conversation_list_service(ctx.user_id)
    # get_conversation_list_service is sync

    # Add meta_data from token usage log if available
    if ctx.token_id > 0:
        for item in conversations:
            # Ensure we do not leak empty meta_data keys
            if "meta_data" in item and not item.get("meta_data"):
                item.pop("meta_data", None)

            conversation_id = item.get("conversation_id")
            if conversation_id:
                try:
                    meta_data = get_latest_usage_metadata(
                        token_id=ctx.token_id,
                        related_id=int(conversation_id),
                        call_function_name="run_chat"
                    )
                    # Only return meta_data when there is a usage log record and meta_data is non-empty
                    if meta_data:
                        item["meta_data"] = meta_data
                    else:
                        item.pop("meta_data", None)
                except Exception as e:
                    logger.warning(f"Failed to get meta_data for conversation {conversation_id}: {str(e)}")
                    item.pop("meta_data", None)

    # Now return internal conversation_id directly
    return {"message": "success", "data": conversations, "requestId": ctx.request_id}


def _format_search_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Format a search source record for API response."""
    search_item = {
        "title": record.get("source_title", ""),
        "text": record.get("source_content", ""),
        "source_type": record.get("source_type", ""),
        "url": record.get("source_location", ""),
        "filename": record.get("source_title", "") if record.get("source_type") == "file" else None,
        "published_date": None,
        "score": float(record["score_overall"]) if record.get("score_overall") is not None else None,
        "tool_sign": record.get("tool_sign", ""),
        "cite_index": record.get("cite_index")
    }

    if record.get("published_date"):
        if hasattr(record["published_date"], "strftime"):
            search_item["published_date"] = record["published_date"].strftime("%Y-%m-%d")
        else:
            search_item["published_date"] = str(record["published_date"])[:10]

    return search_item


async def get_conversation_history_internal(ctx: NorthboundContext, conversation_id: int) -> Dict[str, Any]:
    """Internal helper to get conversation history without logging."""
    history = get_conversation_messages(conversation_id)
    result = []
    for message in history:
        # Parse minio_files from database (stored as JSON string)
        minio_files = []
        raw_minio_files = message.get("minio_files")
        if raw_minio_files:
            try:
                minio_files = json.loads(raw_minio_files) if isinstance(raw_minio_files, str) else raw_minio_files
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Failed to parse minio_files for message {message.get('message_id')}")

        # Fetch search results for this message
        message_id = message.get("message_id")
        search_results = []
        if message_id:
            try:
                search_records = get_source_searches_by_message(message_id, user_id=ctx.user_id)
                search_results = [_format_search_record(r) for r in search_records]
            except Exception as e:
                logger.warning(f"Failed to get search records for message {message_id}: {str(e)}")

        result.append({
            "role": message["message_role"],
            "content": message["message_content"],
            "minio_files": minio_files,
            "search": search_results
        })

    response = {
        "conversation_id": conversation_id,
        "history": result
    }
    return {"message": "success", "data": response, "requestId": ctx.request_id}


async def get_conversation_history(ctx: NorthboundContext, conversation_id: int) -> Dict[str, Any]:
    try:
        return await get_conversation_history_internal(ctx, conversation_id)
    except Exception as e:
        raise Exception(f"Failed to get conversation history for conversation_id {conversation_id}: {str(e)}")


async def get_agent_info_list(ctx: NorthboundContext) -> Dict[str, Any]:
    try:
        agent_info_list = await list_published_agents_impl(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
        )
        # Match the same scope as /agent/published_list: non-asset-owner tenants
        # also get the asset owner's published agents merged in.
        if ctx.tenant_id != ASSET_OWNER_TENANT_ID:
            asset_agent_list = await list_published_agents_impl(
                tenant_id=ASSET_OWNER_TENANT_ID,
                user_id=ctx.user_id,
            )
            agent_info_list.extend(asset_agent_list)
        # Remove internal information that partner don't need
        for agent_info in agent_info_list:
            agent_info.pop("agent_id", None)

        return {"message": "success", "data": agent_info_list, "requestId": ctx.request_id}
    except Exception as e:
        raise Exception(f"Failed to get agent info list for tenant {ctx.tenant_id}: {str(e)}")


async def update_conversation_title(ctx: NorthboundContext, conversation_id: int, title: str, meta_data: Optional[Dict[str, Any]] = None, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    composed_key: Optional[str] = None
    try:
        # Idempotency: avoid concurrent duplicate title update for same conversation
        composed_key = idempotency_key or _build_title_update_idempotency_key(
            ctx.tenant_id,
            conversation_id,
            title,
        )
        await idempotency_start(composed_key)

        update_conversation_title_service(conversation_id, title, ctx.user_id)

        # Log token usage
        if ctx.token_id > 0:
            try:
                log_token_usage(
                    token_id=ctx.token_id,
                    call_function_name="update_conversation_title",
                    related_id=conversation_id,
                    created_by=ctx.user_id,
                    metadata=meta_data
                )
            except Exception as e:
                logger.warning(f"Failed to log token usage: {str(e)}")

        return {
            "message": "success",
            "data": conversation_id,
            "requestId": ctx.request_id,
            "idempotency_key": composed_key,
        }
    except LimitExceededError as _:
        raise LimitExceededError("Duplicate request is still running, please wait.")
    except ConversationNotFoundError:
        raise
    except Exception as e:
        raise Exception(f"Failed to update conversation title for conversation_id {conversation_id}: {str(e)}")
    finally:
        if composed_key:
            asyncio.create_task(_release_idempotency_after_delay(composed_key))


# ==================== Admin User Management ====================


async def admin_create_user(email: str, password: str, role: str, tenant_id: str) -> Dict[str, Any]:
    """
    Create a new user for the specified tenant using admin privileges.

    This function bypasses invitation code requirements and creates users directly
    under the given tenant. Users are automatically added to the tenant's default group.

    Args:
        email: User's email address
        password: User's password (min 6 characters)
        role: User role (USER, DEV, ADMIN)
        tenant_id: Target tenant ID

    Returns:
        Dict containing created user info

    Raises:
        AdminCreateUserException: If user creation fails
    """
    from pydantic import ValidationError
    from email_validator import validate_email, EmailNotValidError
    from utils.auth_utils import get_supabase_admin_client
    from database.user_tenant_db import insert_user_tenant
    from services.group_service import add_user_to_groups, get_tenant_default_group_id
    from services.tool_configuration_service import init_tool_list_for_tenant
    from services.skill_service import init_skill_list_for_tenant
    from consts.exceptions import AdminCreateUserException

    try:
        # Validate email format (skip deliverability check for test/local domains)
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        raise AdminCreateUserException("Invalid email format")

    if len(password) < 6:
        raise AdminCreateUserException("Password must be at least 6 characters")

    valid_roles = ("USER", "DEV", "ADMIN")
    if role not in valid_roles:
        raise AdminCreateUserException(f"Invalid role. Must be one of: {', '.join(valid_roles)}")

    admin_client = get_supabase_admin_client()
    if not admin_client:
        raise AdminCreateUserException("Admin client not available")

    # Check if user already exists
    try:
        existing = admin_client.auth.admin.list_users()
        for user in existing.users:
            if user.email == email:
                raise AdminCreateUserException(f"EMAIL_ALREADY_EXISTS: User with email {email} already exists")
    except AdminCreateUserException:
        raise
    except Exception as e:
        logger.warning(f"Failed to check existing users: {str(e)}")

    # Create user in Supabase auth
    try:
        create_resp = admin_client.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {
                "role": role,
                "tenant_id": tenant_id,
            },
        })
        supabase_user_id = create_resp.user.id
    except Exception as e:
        error_msg = str(e)
        if "already been registered" in error_msg.lower() or "email" in error_msg.lower():
            raise AdminCreateUserException(f"EMAIL_ALREADY_EXISTS: {error_msg}")
        raise AdminCreateUserException(f"Failed to create user: {error_msg}")

    # Create user-tenant relationship
    try:
        insert_user_tenant(
            user_id=supabase_user_id,
            tenant_id=tenant_id,
            user_role=role,
            user_email=email,
        )
    except Exception as e:
        logger.error(f"Failed to create user-tenant relationship: {str(e)}")
        raise AdminCreateUserException(f"Failed to create user-tenant relationship: {str(e)}")

    # Add user to tenant's default group
    try:
        default_group_id = get_tenant_default_group_id(tenant_id)
        if default_group_id:
            add_user_to_groups(supabase_user_id, [default_group_id], supabase_user_id)
            logger.info(f"Added user {email} to default group {default_group_id}")
        else:
            logger.warning(f"No default group found for tenant {tenant_id}, skipping group assignment")
    except Exception as e:
        logger.warning(f"Failed to add user to default group: {str(e)}")

    # Initialize default tools and skills for the new user
    try:
        await init_tool_list_for_tenant(tenant_id, supabase_user_id)
        await init_skill_list_for_tenant(tenant_id, supabase_user_id)
    except Exception as e:
        logger.warning(f"Failed to initialize tools/skills for user {supabase_user_id}: {str(e)}")

    logger.info(f"Successfully created user {email} (id: {supabase_user_id}) in tenant {tenant_id} with role {role}")

    return {
        "user_id": supabase_user_id,
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
    }
