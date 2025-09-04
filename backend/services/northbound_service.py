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
from database.partner_db import (
    add_mapping_id,
    get_external_id_by_internal,
    get_internal_id_by_external
)
from services.agent_service import (
    run_agent_stream,
    stop_agent_tasks,
    list_all_agent_info_impl,
    get_agent_id_by_name
)
from services.conversation_management_service import (
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
# ID mapping helpers
# -----------------------------
async def to_external_conversation_id(internal_id: int) -> str:
    if not internal_id:
        raise Exception("invalid internal conversation id")
    external_id = get_external_id_by_internal(internal_id=internal_id, mapping_type="CONVERSATION")
    if not external_id:
        logger.error(f"cannot find external id for conversation_id: {internal_id}")
        raise Exception("cannot find external id")
    return external_id


async def to_internal_conversation_id(external_id: str) -> int:
    if not external_id:
        raise Exception("invalid external conversation id")
    internal_id = get_internal_id_by_external(external_id=external_id, mapping_type="CONVERSATION")
    return internal_id


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
    external_conversation_id: str,
    agent_name: str,
    query: str,
    idempotency_key: Optional[str] = None
) -> StreamingResponse:
    composed_key: Optional[str] = None
    try:
        # Simple rate limit
        await check_and_consume_rate_limit(ctx.tenant_id)

        internal_conversation_id = await to_internal_conversation_id(external_conversation_id)
        # Add mapping to postgres database
        if internal_conversation_id is None:
            logging.info(f"Conversation {external_conversation_id} not found, creating a new conversation")
            # Create a new conversation and get its internal ID
            new_conversation = create_new_conversation(title="New Conversation", user_id=ctx.user_id)
            internal_conversation_id = new_conversation["conversation_id"]
            # Add the new mapping to the database
            add_mapping_id(internal_id=internal_conversation_id, external_id=external_conversation_id, tenant_id=ctx.tenant_id, user_id=ctx.user_id)

        # Get history according to internal_conversation_id
        history = await get_conversation_history(ctx, external_conversation_id)
        agent_id = await get_agent_id_by_name(agent_name=agent_name, tenant_id=ctx.tenant_id)
        # Idempotency: only prevent concurrent duplicate starts
        composed_key = idempotency_key or _build_idempotency_key(ctx.tenant_id, external_conversation_id, agent_id, query)
        await idempotency_start(composed_key)
        agent_request = AgentRequest(
            conversation_id=internal_conversation_id,
            agent_id=agent_id,
            query=query,
            history=history.get("history"),
            minio_files=None,
            is_debug=False,
        )

    except LimitExceededError as _:
        raise LimitExceededError("Query rate exceeded limit. Please try again later.")
    except UnauthorizedError as _:
        raise UnauthorizedError("Cannot authenticate.")
    except Exception as e:
        raise Exception(f"Failed to start streaming chat for external conversation id {external_conversation_id}: {str(e)}")

    try:
        response = await run_agent_stream(
            agent_request=agent_request,
            http_request=None,
            authorization=ctx.authorization,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
        )
    finally:
        if composed_key:
            asyncio.create_task(_release_idempotency_after_delay(composed_key))

    # Attach request id header
    response.headers["X-Request-Id"] = ctx.request_id
    response.headers["conversation_id"] = external_conversation_id
    return response


async def stop_chat(ctx: NorthboundContext, external_conversation_id: str) -> Dict[str, Any]:
    try:
        internal_id = await to_internal_conversation_id(external_conversation_id)

        stop_result = stop_agent_tasks(internal_id)
        return {"message": stop_result.get("message", "success"), "data": external_conversation_id, "requestId": ctx.request_id}
    except Exception as e:
        raise Exception(f"Failed to stop chat for external conversation id {external_conversation_id}: {str(e)}")


async def list_conversations(ctx: NorthboundContext) -> Dict[str, Any]:
    conversations = get_conversation_list_service(ctx.user_id)
    # get_conversation_list_service is sync
    for item in conversations:
        item["conversation_id"] = await to_external_conversation_id(int(item["conversation_id"]))
    return {"message": "success", "data": conversations, "requestId": ctx.request_id}


async def get_conversation_history(ctx: NorthboundContext, external_conversation_id: str) -> Dict[str, Any]:
    internal_id = await to_internal_conversation_id(external_conversation_id)

    history = get_conversation_messages(internal_id)
    # Remove unnecessary fields
    result = []
    for message in history:
        result.append({
            "role": message["message_role"],
            "content": message["message_content"]
        })

    response = {
        "conversation_id": external_conversation_id,
        "history": result
    }
    # Ensure external id in response
    return {"message": "success", "data": response, "requestId": ctx.request_id}


async def get_agent_info_list(ctx: NorthboundContext) -> Dict[str, Any]:
    try:
        agent_info_list = await list_all_agent_info_impl(tenant_id=ctx.tenant_id)
        # Remove internal information that partner don't need
        for agent_info in agent_info_list:
            agent_info.pop("agent_id", None)
        return {"message": "success", "data": agent_info_list, "requestId": ctx.request_id}
    except Exception as e:
        raise Exception(f"Failed to get agent info list for tenant {ctx.tenant_id}: {str(e)}")


async def update_conversation_title(ctx: NorthboundContext, external_conversation_id: str, title: str, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    composed_key: Optional[str] = None
    try:
        internal_id = await to_internal_conversation_id(external_conversation_id)

        # Idempotency: avoid concurrent duplicate title update for same conversation
        composed_key = idempotency_key or _build_idempotency_key(ctx.tenant_id, external_conversation_id, title)
        await idempotency_start(composed_key)

        update_conversation_title_service(internal_id, title, ctx.user_id)
        return {
            "message": "success",
            "data": external_conversation_id,
            "requestId": ctx.request_id,
            "idempotency_key": composed_key,
        }
    except LimitExceededError as _:
        raise LimitExceededError("Duplicate request is still running, please wait.")
    except Exception as e:
        raise Exception(f"Failed to update conversation title for external conversation id {external_conversation_id}: {str(e)}")
    finally:
        if composed_key:
            asyncio.create_task(_release_idempotency_after_delay(composed_key))
