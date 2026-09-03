import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from os.path import basename
from typing import Any, Dict, List, Optional

from fastapi import UploadFile
from fastapi.responses import StreamingResponse


from consts.const import (
    AIDP_API_KEY,
    AIDP_SERVER_URL,
    ASSET_OWNER_TENANT_ID,
    NORTHBOUND_IDEMPOTENCY_TTL_SECONDS,
    NORTHBOUND_RATE_LIMIT_ENABLED,
    NORTHBOUND_RATE_LIMIT_PER_MINUTE,
)
from consts.exceptions import (
    AppException,
    RuntimeMetadataValidationError,
    LimitExceededError,
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    RuntimeUpstreamError,
    UnauthorizedError,
    ConversationNotFoundError,
)
from consts.error_code import ErrorCode, RuntimeMetadataValidationCode
from consts.model import AgentRequest, ToolParamsRequest
from database.knowledge_db import get_knowledge_info_by_tenant_id
from database.conversation_db import get_conversation_list, get_conversation_messages
from database.token_db import get_latest_usage_metadata, log_token_usage
from management.services.agent.service import (
    get_agent_by_name_impl,
)
from services.runtime_proxy_service import forward_agent_run, forward_agent_stop
from services.runtime_state_service import runtime_state_service
from services.agent_version_service import list_published_agents_impl
from services.knowledge_scope_service import (
    AIDP_TOOL_CLASS,
    LOCAL_TOOL_CLASS,
    get_agent_knowledge_capabilities,
)
from management.services.knowledge_base.service import ElasticSearchService
from management.services.model.resolver import get_model_descriptor
from services.conversation_management_service import (
    save_conversation_user,
    create_new_conversation,
    generate_conversation_title_service,
    update_conversation_title as update_conversation_title_service,
)
from services.model_management_service import list_models_for_tenant
from utils.runtime_metadata_utils import (
    runtime_metadata_hash,
    validate_runtime_metadata,
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
_IDEMPOTENCY_LOCK = asyncio.Lock()

_RATE_STATE: Dict[str, Dict[str, int]] = {}
_RATE_LOCK = asyncio.Lock()


def _now_seconds() -> float:
    return time.time()


def _minute_bucket(ts: Optional[float] = None) -> str:
    t = int((ts or _now_seconds()) // 60)
    return str(t)


async def idempotency_start(key: str, ttl_seconds: Optional[int] = None) -> None:
    ttl = ttl_seconds or NORTHBOUND_IDEMPOTENCY_TTL_SECONDS
    if runtime_state_service.enabled:
        try:
            acquired = await runtime_state_service.acquire_idempotency_async(key, ttl)
        except Exception:
            logger.exception("Northbound idempotency Redis operation failed")
            raise LimitExceededError("Idempotency service is unavailable. Please try again later.")
        if not acquired:
            raise LimitExceededError("Duplicate request is still running, please wait.")
        return

    async with _IDEMPOTENCY_LOCK:
        # purge expired
        now = _now_seconds()
        expired = [k for k, v in _IDEMPOTENCY_RUNNING.items() if now - v > ttl]
        for k in expired:
            _IDEMPOTENCY_RUNNING.pop(k, None)
        if key in _IDEMPOTENCY_RUNNING:
            raise LimitExceededError("Duplicate request is still running, please wait.")
        _IDEMPOTENCY_RUNNING[key] = now


async def idempotency_end(key: str) -> None:
    if runtime_state_service.enabled:
        try:
            await runtime_state_service.release_idempotency_async(key)
        except Exception as exc:
            logger.warning("Northbound idempotency release failed: %s", exc)
        return

    async with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY_RUNNING.pop(key, None)


async def _release_idempotency_after_delay(key: str, seconds: int = 3) -> None:
    await asyncio.sleep(seconds)
    await idempotency_end(key)


async def check_and_consume_rate_limit(tenant_id: str) -> None:
    if not NORTHBOUND_RATE_LIMIT_ENABLED:
        return

    if runtime_state_service.enabled:
        try:
            await runtime_state_service.consume_rate_limit_async(
                tenant_id=tenant_id,
                limit_per_minute=NORTHBOUND_RATE_LIMIT_PER_MINUTE,
            )
            return
        except ValueError:
            raise LimitExceededError("Query rate exceeded limit. Please try again later")
        except Exception:
            logger.exception("Northbound rate limit Redis operation failed")
            raise LimitExceededError("Rate limit service is unavailable. Please try again later.")

    bucket = _minute_bucket()
    async with _RATE_LOCK:
        state = _RATE_STATE.setdefault(tenant_id, {})
        count = state.get(bucket, 0)
        if count >= NORTHBOUND_RATE_LIMIT_PER_MINUTE:
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


async def start_streaming_chat(
    ctx: NorthboundContext,
    conversation_id: Optional[int],
    agent_name: str,
    query: str,
    attachments: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    meta_data: Optional[Dict[str, Any]] = None,
    tool_params: Optional[ToolParamsRequest] = None,
    model_id: Optional[int] = None,
    idempotency_key: Optional[str] = None
) -> StreamingResponse:
    new_conversation_data: Optional[Dict[str, Any]] = None
    try:
        if metadata is not None:
            try:
                validate_runtime_metadata(metadata)
            except RuntimeMetadataValidationError as exc:
                error_code = (
                    ErrorCode.CHAT_METADATA_TOO_LARGE
                    if exc.code == RuntimeMetadataValidationCode.METADATA_TOO_LARGE
                    else ErrorCode.CHAT_METADATA_INVALID
                )
                raise AppException(
                    error_code,
                    details={"reason": exc.code.value},
                ) from exc
        # Simple rate limit
        await check_and_consume_rate_limit(ctx.tenant_id)

        agent_info = get_agent_by_name_impl(agent_name=agent_name, tenant_id=ctx.tenant_id)
        agent_id = agent_info["agent_id"]
        latest_version_no = agent_info["latest_version_no"]
        if conversation_id is None:
            logging.info("No conversation_id provided, creating a new conversation")
            new_conversation_data = create_new_conversation(
                title="New Conversation",
                user_id=ctx.user_id,
                agent_id=agent_id,
            )
            conversation_id = new_conversation_data["conversation_id"]
            logging.info(f"Created new conversation with id: {conversation_id}")

        internal_conversation_id = conversation_id

        # Get history according to internal_conversation_id
        history_resp = await get_conversation_history_internal(ctx, internal_conversation_id)
        normalized_attachments = _normalize_northbound_attachments(
            attachments=attachments,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
        )
        # Idempotency: only prevent concurrent duplicate starts
        metadata_key = "inherit" if metadata is None else runtime_metadata_hash(metadata)
        composed_key = idempotency_key or _build_idempotency_key(
            ctx.tenant_id,
            str(conversation_id),
            agent_id,
            query,
            metadata_key,
        )
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
            version_no=latest_version_no,
            metadata=metadata,
            enable_automation_tool=False,
        )
        agent_request.__dict__["_runtime_metadata_entrypoint"] = "northbound"

        # Persist the user message off the event loop before starting the stream.
        # We deliberately keep this synchronous step (not async submit) for
        # northbound reliability -- external callers may not have SSE reconnect
        # capability, so a late INSERT failure after the stream starts would
        # silently lose the user message.  asyncio.to_thread avoids blocking
        # the event loop while preserving the synchronous commit semantics.
        try:
            await asyncio.to_thread(
                save_conversation_user,
                agent_request,
                ctx.user_id,
                ctx.tenant_id,
            )
        except Exception as e:
            raise Exception(f"Failed to persist user message: {str(e)}")

    except LimitExceededError as exc:
        raise LimitExceededError(str(exc))
    except UnauthorizedError as _:
        raise UnauthorizedError("Cannot authenticate.")
    except AppException:
        raise
    except Exception as e:
        raise Exception(f"Failed to start streaming chat for conversation_id {conversation_id}: {str(e)}")

    try:
        response = await forward_agent_run(
            agent_request=agent_request,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
        )
    finally:
        if composed_key:
            asyncio.create_task(_release_idempotency_after_delay(composed_key))

    # Preserve request metadata for conversation continuation and usage auditing.
    if ctx.token_id > 0:
        try:
            log_token_usage(
                token_id=ctx.token_id,
                call_function_name="run_chat",
                related_id=conversation_id,
                created_by=ctx.user_id,
                metadata=meta_data,
            )
        except Exception as e:
            logger.warning(f"Failed to log token usage: {str(e)}")

    # Attach northbound response headers used by streaming clients and proxies.
    response.headers["X-Request-Id"] = ctx.request_id
    response.headers["conversation_id"] = str(conversation_id)
    response.headers["X-Accel-Buffering"] = "no"

    if new_conversation_data is not None:
        original_body_iterator = response.body_iterator

        async def body_iterator_with_conversation_created():
            yield ("data: " + json.dumps({"type": "conversation_created", "content": {"conversation_id": conversation_id}}, ensure_ascii=False) + "\n\n").encode("utf-8")
            async for chunk in original_body_iterator:
                yield chunk

        response.body_iterator = body_iterator_with_conversation_created()

    return response


async def stop_chat(ctx: NorthboundContext, conversation_id: int, meta_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        stop_result = await forward_agent_stop(
            conversation_id=conversation_id,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
        )

        if ctx.token_id > 0:
            try:
                log_token_usage(
                    token_id=ctx.token_id,
                    call_function_name="stop_chat_stream",
                    related_id=conversation_id,
                    created_by=ctx.user_id,
                    metadata=meta_data,
                )
            except Exception as e:
                logger.warning(f"Failed to log token usage: {str(e)}")

        return {"message": stop_result.get("message", "success"), "data": conversation_id, "requestId": ctx.request_id}
    except (
        RuntimeServiceTimeoutError,
        RuntimeServiceUnavailableError,
        RuntimeUpstreamError,
    ):
        raise
    except Exception as e:
        raise Exception(f"Failed to stop chat for conversation_id {conversation_id}: {str(e)}")


async def list_conversations(ctx: NorthboundContext) -> Dict[str, Any]:
    conversations = get_conversation_list(ctx.user_id)

    # Now return internal conversation_id directly
    return {"message": "success", "data": conversations, "requestId": ctx.request_id}


async def list_configured_models(ctx: NorthboundContext) -> Dict[str, Any]:
    """List the models configured for the authenticated tenant."""
    models = await list_models_for_tenant(ctx.tenant_id)
    return {"message": "success", "data": models, "requestId": ctx.request_id}


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
                logger.warning(
                    "Failed to parse minio_files for message %s",
                    message.get("message_id"),
                )
        result.append({
            "role": message["message_role"],
            "content": message["message_content"],
            "minio_files": minio_files,
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


async def _get_visible_published_agents(ctx: NorthboundContext) -> list[dict]:
    """Return published agents visible to the northbound caller."""
    agent_info_list = [
        dict(agent)
        for agent in await list_published_agents_impl(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
        )
    ]
    for agent in agent_info_list:
        agent["_northbound_tenant_id"] = ctx.tenant_id
    if ctx.tenant_id != ASSET_OWNER_TENANT_ID:
        asset_owner_agents = [
            dict(agent)
            for agent in await list_published_agents_impl(
                tenant_id=ASSET_OWNER_TENANT_ID,
                user_id=ctx.user_id,
            )
        ]
        for agent in asset_owner_agents:
            agent["_northbound_tenant_id"] = ASSET_OWNER_TENANT_ID
        agent_info_list.extend(asset_owner_agents)
    return agent_info_list


async def get_agent_info_list(ctx: NorthboundContext) -> Dict[str, Any]:
    try:
        agent_info_list = await _get_visible_published_agents(ctx)
        for agent_info in agent_info_list:
            agent_info.pop("agent_id", None)
            agent_info.pop("_northbound_tenant_id", None)

        return {"message": "success", "data": agent_info_list, "requestId": ctx.request_id}
    except Exception as e:
        raise Exception(f"Failed to get agent info list for tenant {ctx.tenant_id}: {str(e)}")


async def get_agent_info_by_name_for_northbound(
    ctx: NorthboundContext,
    agent_name: str,
) -> Dict[str, Any]:
    """Return one visible published agent selected by its exact agent name."""
    if not agent_name.strip():
        raise ValueError("agent_name is required")

    try:
        agent_info_list = await _get_visible_published_agents(ctx)
        agent_info = next(
            (
                item for item in agent_info_list
                if item.get("name") == agent_name
            ),
            None,
        )
        if agent_info is None:
            raise LookupError(f"Published agent not found: {agent_name}")

        result = dict(agent_info)
        result.pop("agent_id", None)
        result.pop("_northbound_tenant_id", None)
        return {"message": "success", "data": result, "requestId": ctx.request_id}
    except (ValueError, LookupError):
        raise
    except Exception as e:
        raise Exception(
            f"Failed to get agent info for agent_name {agent_name} in tenant {ctx.tenant_id}: {str(e)}"
        )


async def get_agent_knowledge_bases_for_northbound(
    ctx: NorthboundContext,
    agent_name: str,
) -> Dict[str, Any]:
    """Return knowledge bases the caller may pass to the selected agent tool."""
    if not agent_name.strip():
        raise ValueError("agent_name is required")

    visible_agents = await _get_visible_published_agents(ctx)
    agent = next(
        (item for item in visible_agents if item.get("name") == agent_name),
        None,
    )
    if agent is None:
        raise LookupError(f"Published agent not found: {agent_name}")

    agent_tenant_id = str(agent.get("_northbound_tenant_id") or ctx.tenant_id)
    agent_id = int(agent["agent_id"])
    version_no = agent.get("current_version_no")
    capabilities = get_agent_knowledge_capabilities(
        agent_id=agent_id,
        tenant_id=agent_tenant_id,
        version_no=int(version_no) if version_no is not None else None,
        user_id=ctx.user_id,
    )
    local_enabled = bool(capabilities["sources"]["local"]["enabled"])
    aidp_enabled = bool(capabilities["sources"]["aidp"]["enabled"])
    if local_enabled and aidp_enabled:
        raise ValueError(
            "The agent enables both local and AIDP knowledge retrieval."
        )

    if not local_enabled and not aidp_enabled:
        return {
            "message": "success",
            "data": {
                "agent_name": agent_name,
                "source": None,
                "tool_name": None,
                "range_parameter": None,
                "max_select": 0,
                "default_selected_ids": [],
                "knowledge_bases": [],
            },
            "requestId": ctx.request_id,
        }

    if local_enabled:
        records = get_knowledge_info_by_tenant_id(agent_tenant_id)
        candidate_indices = [
            str(record["index_name"])
            for record in records
            if record.get("index_name")
            and record.get("knowledge_sources") != "datamate"
        ]
        accessible_indices = set(
            ElasticSearchService.filter_accessible_indices(
                candidate_indices,
                user_id=ctx.user_id,
                tenant_id=agent_tenant_id,
            )
        )
        items = [
            {
                "id": str(record["index_name"]),
                "knowledge_id": str(record["knowledge_id"]),
                "name": str(record.get("knowledge_name") or record["index_name"]),
                "embedding_model": str(record.get("embedding_model_name") or ""),
                "embedding_model_id": record.get("embedding_model_id"),
                "is_multimodal": get_model_descriptor(
                    record.get("embedding_model_id"), agent_tenant_id
                ).is_multimodal,
            }
            for record in records
            if str(record.get("index_name") or "") in accessible_indices
        ]
        source = "local"
        tool_name = LOCAL_TOOL_CLASS
        range_parameter = "index_names"
    else:
        from ext_components.aidp.services.aidp_access_service import (
            resolve_current_aidp_access,
        )
        from ext_components.aidp.services.aidp_service import (
            get_aidp_kb_impl,
        )

        snapshot = await asyncio.to_thread(
            resolve_current_aidp_access,
            server_url=AIDP_SERVER_URL,
            api_key=AIDP_API_KEY,
            user_id=ctx.user_id,
            tenant_id=agent_tenant_id,
            aidp_tenant_id="aidp",
        )
        rows = snapshot.accessible_rows
        items = []
        for row in rows:
            detail: Dict[str, Any] = {}
            resource_status = str(row.get("resource_status") or "ACTIVE")
            try:
                detail = await asyncio.to_thread(
                    get_aidp_kb_impl,
                    AIDP_SERVER_URL,
                    AIDP_API_KEY,
                    str(row["kb_id"]),
                ) or {}
                resource_status = "ACTIVE"
            except Exception as exc:
                logger.warning(
                    "AIDP detail fetch failed for northbound knowledge list kb_id=%s: %s",
                    row["kb_id"],
                    exc,
                )
                resource_status = "UNAVAILABLE"
            items.append({
                "id": str(row["kb_id"]),
                "name": str(
                    detail.get("kds_name")
                    or detail.get("name")
                    or row.get("kds_name")
                    or row.get("name")
                    or row["kb_id"]
                ),
                "document_count": int(
                    detail.get("document_count") or row.get("document_count") or 0
                ),
                "chunk_count": int(detail.get("chunk_count") or row.get("chunk_count") or 0),
                "is_multimodal": (
                    detail.get("caption_enable", row.get("caption_enable")) in (1, "1", True)
                ),
                "resource_status": resource_status,
            })
        source = "aidp"
        tool_name = AIDP_TOOL_CLASS
        range_parameter = "kds_list"

    source_capabilities = capabilities["sources"][source]
    return {
        "message": "success",
        "data": {
            "agent_name": agent_name,
            "source": source,
            "tool_name": tool_name,
            "range_parameter": range_parameter,
            "max_select": source_capabilities["max_select"],
            "default_selected_ids": source_capabilities["default_range_values"],
            "knowledge_bases": items,
        },
        "requestId": ctx.request_id,
    }


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

        if ctx.token_id > 0:
            try:
                log_token_usage(
                    token_id=ctx.token_id,
                    call_function_name="update_conversation_title",
                    related_id=conversation_id,
                    created_by=ctx.user_id,
                    metadata=meta_data,
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


async def generate_conversation_title(
    ctx: NorthboundContext,
    conversation_id: int,
    question: str,
    language: str,
) -> Dict[str, Any]:
    """Generate and persist a conversation title from the user's question."""
    title = await generate_conversation_title_service(
        conversation_id=conversation_id,
        question=question,
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        language=language,
    )
    return {"message": "success", "data": title, "requestId": ctx.request_id}
