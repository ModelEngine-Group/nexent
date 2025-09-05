"""High-level Memory CRUD helpers for both backend apps and external callers.

All operations eventually delegate to :pyfunc:`nexent.memory.memory_core.get_memory_instance`,
thus avoiding any HTTP round-trips.  The module purposely contains no FastAPI
or networking code so that it can be used in any context (sync workers, async
handlers, CLI scripts, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .memory_core import get_memory_instance
from .memory_utils import build_memory_identifiers


logger = logging.getLogger("memory_service")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _filter_by_memory_level(memory_level: str, raw_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    根据 memory_level 过滤搜索或列表结果，仅供模块内部使用。

    参数:
        memory_level: "tenant" | "user" | "agent" | "user_agent"
        raw_results:   需要过滤的结果列表

    返回:
        过滤后的结果列表
    """
    if memory_level in {"tenant", "user"}:
        return [r for r in raw_results if not r.get("agent_id")]
    elif memory_level in {"agent", "user_agent"}:
        return [r for r in raw_results if r.get("agent_id")]
    else:
        raise ValueError("Unsupported memory level: " + memory_level)

# ---------------------------------------------------------------------------
# Public CRUD helpers
# ---------------------------------------------------------------------------


async def add_memory(
    messages: List[Dict[str, Any]] | str,
    memory_level: str,
    memory_config: Dict[str, Any],
    tenant_id: str,
    user_id: str,
    agent_id: Optional[str] = None,
    infer: bool = True
) -> Any:
    """Add memory *messages* for the given *memory_level*.

    Parameters match those of the original FastAPI endpoint.
    """
    mem_user_id = build_memory_identifiers(memory_level=memory_level, user_id=user_id, tenant_id=tenant_id)
    memory = await get_memory_instance(memory_config)

    if memory_level in {"tenant", "user"}:
        return await memory.add(messages, user_id=mem_user_id, infer=infer)
    elif memory_level in {"agent", "user_agent"}:
        return await memory.add(messages, agent_id=agent_id, user_id=mem_user_id, infer=infer)
    else:
        raise ValueError("Unsupported memory level: " + memory_level)


async def add_memory_in_levels(
    messages: List[Dict[str, Any]] | str,
    memory_config: Dict[str, Any],
    tenant_id: str,
    user_id: str,
    agent_id: str,
    memory_levels: List[str] = ["agent", "user_agent"],
):
    """
    Add memory across the specified levels concurrently, then merge results.

    Args:
        ...
        memory_levels: List[str: "tenant"|"agent"|"user"|"user_agent"]

    Returns:
        {"results": [
            {"id": "...", "memory": "...", "event": "ADD"|"DELETE"|"UPDATE"|"NONE"},
            ...
        ]}
    """
    event_priority = {"DELETE": 3, "ADD": 2, "UPDATE": 1, "NONE": 0}
    result_list: List[Dict[str, Any]] = []
    # Mapping from memory id to its index in result_list
    id2idx: Dict[str, int] = {}

    async def _add_level(level: str) -> List[Dict[str, Any]]:
        try:
            if level not in {"tenant", "user", "agent", "user_agent"}:
                raise ValueError("Unsupported memory level: " + level)
            res = await add_memory(
                messages=messages,
                memory_level=level,
                memory_config=memory_config,
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=agent_id,
                infer=True,
            )
            items = res.get("results", [])
            logger.debug(f"Memory add results for level '{level}': {items}")
            return items
        except Exception as e:
            logger.error(f"Error adding memory in level '{level}': {e}")
            return []

    tasks = [asyncio.create_task(_add_level(level)) for level in memory_levels]
    all_level_results = await asyncio.gather(*tasks)

    for results in all_level_results:
        for item in results:
            item_id = item.get("id")
            existing_idx = id2idx.get(item_id)
            if existing_idx is None:
                result_list.append(item)
                id2idx[item_id] = len(result_list) - 1
            else:
                existing_event = result_list[existing_idx].get("event")
                new_event = item.get("event")
                if event_priority.get(new_event, 0) > event_priority.get(existing_event, 0):
                    result_list[existing_idx] = item

    return {"results": result_list}


async def search_memory(
    query_text: str,
    memory_level: str,
    memory_config: Dict[str, Any],
    tenant_id: str,
    user_id: str,
    agent_id: Optional[str] = None,
    top_k: int = 5,
    threshold: Optional[float] = 0.65,
) -> Any:
    """Search memory and return *mem0* search results list."""
    mem_user_id = build_memory_identifiers(memory_level=memory_level, user_id=user_id, tenant_id=tenant_id)
    memory = await get_memory_instance(memory_config)
    if memory_level in {"tenant", "user"}:
        search_res = await memory.search(
            query=query_text,
            limit=top_k,
            threshold=threshold,
            user_id=mem_user_id,
        )
    elif memory_level in {"agent", "user_agent"}:
        search_res = await memory.search(
            query=query_text,
            limit=top_k,
            threshold=threshold,
            user_id=mem_user_id,
            agent_id=agent_id,
        )
    else:
        raise ValueError("Unsupported memory level: " + memory_level)

    raw_results = search_res.get("results", [])
    if asyncio.iscoroutine(raw_results):
        raw_results = await raw_results
    return {"results": _filter_by_memory_level(memory_level, raw_results)}


async def search_memory_in_levels(
    query_text: str,
    memory_config: Dict[str, Any],
    tenant_id: str,
    user_id: str,
    agent_id: str,
    top_k: int = 5,
    threshold: Optional[float] = 0.65,
    memory_levels: List[str] = ["tenant", "user", "agent", "user_agent"],
):
    """
    Search memory according to user's preference for all four levels.
    Args:
        ...
        memory_levels: List[str: "tenant"|"agent"|"user"|"user_agent"]
    Returns:
        {"results": [
            {'id': '...', 'memory': '...', 'score': '...', 'memory_level': '...'},
            ...
        ]}
    """
    result_list = []

    logger.info(f"Searching memory in levels: {memory_levels}")

    async def _search_level(level: str):
        try:
            res = await search_memory(
                query_text,
                level,
                memory_config,
                tenant_id,
                user_id,
                agent_id,
                top_k,
                threshold,
            )
            raw = res.get("results", [])
            return [{**item, "memory_level": level} for item in raw]
        except Exception as e:
            logger.error(f"search_memory failed on level '{level}': {e}")
            return []

    # Run searches concurrently and preserve order of memory_levels
    tasks = [asyncio.create_task(_search_level(level)) for level in memory_levels]
    all_level_results = await asyncio.gather(*tasks)

    for level_results in all_level_results:
        result_list.extend(level_results)

    return {"results": result_list}


async def list_memory(
    memory_level: str,
    memory_config: Dict[str, Any],
    tenant_id: str,
    user_id: str,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a list of memories for the specified *memory_level* and *agent_id*."""
    mem_user_id = build_memory_identifiers(memory_level=memory_level, user_id=user_id, tenant_id=tenant_id)
    memory = await get_memory_instance(memory_config)

    search_res = await memory.get_all(user_id=mem_user_id, agent_id=agent_id)
    raw_results = search_res.get("results", [])
    if asyncio.iscoroutine(raw_results):
        raw_results = await raw_results

    all_results_list = _filter_by_memory_level(memory_level, raw_results)

    return {"items": all_results_list, "total": len(all_results_list)}


async def delete_memory(memory_id: str, memory_config: Dict[str, Any]) -> Any:
    """Delete a single memory by *memory_id*."""
    memory = await get_memory_instance(memory_config)
    if hasattr(memory, "delete"):
        return await memory.delete(memory_id=memory_id)
    raise AttributeError("Memory implementation does not support delete()")


async def clear_memory(
    memory_level: str,
    memory_config: Dict[str, Any],
    tenant_id: str,
    user_id: str,
    agent_id: Optional[str] = None,
) -> Dict[str, int]:
    """Clear all memories for the specified *memory_level* and *agent_id*."""
    mem_user_id = build_memory_identifiers(memory_level=memory_level, user_id=user_id, tenant_id=tenant_id)
    memory = await get_memory_instance(memory_config)
    search_res = await memory.get_all(user_id=mem_user_id, agent_id=agent_id)
    raw_results = search_res.get("results", [])
    if asyncio.iscoroutine(raw_results):
        raw_results = await raw_results

    all_memories = _filter_by_memory_level(memory_level, raw_results)

    deleted_count = 0
    for mem in all_memories:
        try:
            await memory.delete(memory_id=mem.get("id"))
            deleted_count += 1
        except Exception as exc:
            logger.warning("Failed to delete memory %s: %s", mem.get("id"), exc)

    return {"deleted_count": deleted_count, "total_count": len(all_memories)}


async def reset_all_memory(memory_config: Dict[str, Any]) -> bool:
    """ Reset all memory in the memory store. """
    try:
        memory = await get_memory_instance(memory_config)
        await memory.reset()
        return True
    except Exception as e:
        logger.error(f"Failed to reset all memory: {e}")
        return False
