# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind prepared Memory tools to an admitted Runtime conversation."""

from contracts.agentos import AgentMemoryStore
from infrastructure.agent_tool_config import STORE_MEMORY_TOOL, build_store_memory_tool
from infrastructure.agentos_identity import ServicePrincipal
from nexent.memory.service import MemoryService
from runtime.agentos.memory import get_memory_store_service


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
        return receipt.model_dump()

    tool = build_store_memory_tool({
        "tenant_id": actor.tenant_id, "user_id": actor.user_id, "agent_id": str(resource.agent_id),
        "conversation_id": str(conversation_id), "memory_service": MemoryService(backend_store=store),
    })
    return {STORE_MEMORY_TOOL: tool}, events
