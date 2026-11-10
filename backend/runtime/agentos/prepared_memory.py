# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind prepared Memory tools to an admitted Runtime conversation."""

import logging

import httpx

from contracts.agentos import AgentMemoryStore, AgentMemoryStored, ManagementOperation
from contracts.constants import environment
from infrastructure.agent_tool_config import STORE_MEMORY_TOOL, build_store_memory_tool
from infrastructure.agentos_identity import AgentOSIdentityError, ServicePrincipal, sign_call
from nexent.memory.service import MemoryService
from runtime.agentos.memory import get_memory_store_service

logger = logging.getLogger(__name__)
_INGEST_TIMEOUT = httpx.Timeout(20, connect=3)


async def notify_memory_stored(notice: AgentMemoryStored, actor: ServicePrincipal) -> None:
    operation = ManagementOperation.MEMORY_STORED
    body = notice.model_dump_json().encode()
    try:
        token = sign_call(operation, body, actor)
        async with httpx.AsyncClient(timeout=_INGEST_TIMEOUT, trust_env=False, follow_redirects=False) as client:
            response = await client.post(
                f"{environment.MANAGEMENT_AGENTOS_URL.rstrip('/')}/api{operation.value}", content=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            response.raise_for_status()
    except (AgentOSIdentityError, httpx.HTTPError) as exc:
        logger.warning("External Memory notification failed memory_id=%s error=%s", notice.memory_id, type(exc).__name__)


def materialize_memory(resource, actor: ServicePrincipal, conversation_id: int | None):
    bindings = [tool for tool in resource.tools if tool.tool_id == STORE_MEMORY_TOOL]
    items = resource.evaluation_options.context_items if resource.evaluation_options else None
    memory_context = any(item.get("type") in {"memory", "long_term_memory"} for item in items or [])
    search = resource.memory_search
    if (search is not None or bindings or memory_context) and not conversation_id:
        raise ValueError("Prepared Memory requires a persistent conversation")
    if memory_context and search is None:
        raise ValueError("Prepared Memory context requires a search binding")
    events = search.observer_events() if search is not None else []
    if not bindings:
        return {}, events
    if len(bindings) != 1 or bindings[0].version != "1" or bindings[0].parameters or bindings[0].credential_ref:
        raise ValueError("Unsupported prepared Memory store binding")

    async def store(payload):
        receipt = await get_memory_store_service().store(AgentMemoryStore(
            agent_id=resource.agent_id, conversation_id=conversation_id, content=payload["content"],
            idempotency_key=payload["idempotency_key"],
        ), actor)
        await notify_memory_stored(AgentMemoryStored(
            memory_id=receipt.memory_id, agent_id=resource.agent_id, conversation_id=conversation_id,
        ), actor)
        return receipt.model_dump()

    tool = build_store_memory_tool({
        "tenant_id": actor.tenant_id, "user_id": actor.user_id, "agent_id": str(resource.agent_id),
        "conversation_id": str(conversation_id), "memory_service": MemoryService(backend_store=store),
    })
    return {STORE_MEMORY_TOOL: tool}, events
