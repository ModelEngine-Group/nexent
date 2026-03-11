import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi.responses import StreamingResponse

from consts.exceptions import (
    LimitExceededError,
    UnauthorizedError,
)
from consts.model import AgentRequest
from database.conversation_db import get_conversation_messages
from database.token_db import log_token_usage, get_latest_usage_metadata
from services.agent_service import (
    run_agent_stream,
    stop_agent_tasks,
    list_all_agent_info_impl,
    get_agent_id_by_name
)
from services.conversation_management_service import (
    save_conversation_user,
    get_conversation_list_service,
    create_new_conversation,
    update_conversation_title as update_conversation_title_service,
)

logger = logging.getLogger("northbound_service")


@dataclass
class NorthboundContext:
    request_id: str
    tenant_id: str
    user_id: str
    authorization: str
    token_id: int = 0


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
    meta_data: Optional[Dict[str, Any]] = None,
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
        # Idempotency: only prevent concurrent duplicate starts
        composed_key = idempotency_key or _build_idempotency_key(ctx.tenant_id, str(conversation_id), agent_id, query)
        await idempotency_start(composed_key)
        agent_request = AgentRequest(
            conversation_id=internal_conversation_id,
            agent_id=agent_id,
            query=query,
            history=(history_resp.get("data", {})).get("history", []),
            minio_files=None,
            is_debug=False,
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


async def get_conversation_history_internal(ctx: NorthboundContext, conversation_id: int) -> Dict[str, Any]:
    """Internal helper to get conversation history without logging."""
    history = get_conversation_messages(conversation_id)
    # Remove unnecessary fields
    result = []
    for message in history:
        result.append({
            "role": message["message_role"],
            "content": message["message_content"]
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
        agent_info_list = await list_all_agent_info_impl(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
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
        composed_key = idempotency_key or _build_idempotency_key(ctx.tenant_id, str(conversation_id), title)
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
    except Exception as e:
        raise Exception(f"Failed to update conversation title for conversation_id {conversation_id}: {str(e)}")
    finally:
        if composed_key:
            asyncio.create_task(_release_idempotency_after_delay(composed_key))
