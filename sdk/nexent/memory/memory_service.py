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
    Filter search or list results by memory_level

    args:
        memory_level: "tenant" | "user" | "agent" | "user_agent"
        raw_results:   The list of results to filter

    return:
        The filtered list of results
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


async def clear_model_memories(
    es_core: Any,
    model_repo: str,
    model_name: str,
    embedding_dims: int,
    base_memory_config: Dict[str, Any],
) -> bool:
    """Clear all memories and drop ES index for a specific embedding model configuration.

    This helper follows the index naming and configuration logic used by the backend's
    memory utilities, while remaining SDK-only and transport-agnostic.

    Args:
        es_core: An initialized Elasticsearch core instance (must expose ``client.indices`` and ``delete_index``).
        model_repo: Optional repository/namespace of the embedding model (e.g., "jina-ai"). Empty if none.
        model_name: The embedding model name (e.g., "jina-embeddings-v2-base-en").
        embedding_dims: The embedding vector dimension for this model configuration.
        base_memory_config: A fully-validated memory config to use as a template. This function will not mutate it,
            but will derive an adjusted config with the correct collection name and embedding dims for the operation.

    Returns:
        True if the cleanup completed (or nothing needed to be done). False on hard failures.
    """
    try:
        repo_part = (model_repo or "").strip().lower()
        name_part = (model_name or "").strip().lower()
        if not name_part:
            raise ValueError("model_name is required to clear model memories")

        # Follow backend/utils/memory_utils.py naming: mem0_{repo}_{name}_{dims} or mem0_{name}_{dims}
        if repo_part:
            index_name = f"mem0_{repo_part}_{name_part}_{embedding_dims}"
        else:
            index_name = f"mem0_{name_part}_{embedding_dims}"

        # 1) If index does not exist in ES, nothing to do
        try:
            es_exists = es_core.client.indices.exists(index=index_name)
        except Exception:
            # If existence check fails, proceed defensively to attempt cleanup via mem0 then ES delete
            es_exists = True

        if not es_exists:
            return True

        # 2) Build a config bound to this index and embedding dims without mutating the base config
        #    Ensure required keys exist; get_memory_instance will validate again
        memory_config: Dict[str, Any] = {
            **base_memory_config,
            "embedder": {
                **base_memory_config.get("embedder", {}),
                "provider": base_memory_config.get("embedder", {}).get("provider", "openai"),
                "config": {
                    **base_memory_config.get("embedder", {}).get("config", {}),
                    # Keep model/base_url/api_key from base, only adjust dims to match the index
                    "embedding_dims": embedding_dims,
                },
            },
            "vector_store": {
                **base_memory_config.get("vector_store", {}),
                "provider": "elasticsearch",
                "config": {
                    **base_memory_config.get("vector_store", {}).get("config", {}),
                    "collection_name": index_name,
                    "embedding_model_dims": embedding_dims,
                },
            },
        }

        # 3) Reset all memory for this config via mem0
        try:
            logger.debug(f"Start to clear all memories in {model_repo}")
            await reset_all_memory(memory_config)
        except Exception:
            # Keep going to ensure ES index is dropped even if mem0 reset had issues
            pass

        # 4) Drop ES index
        try:
            es_core.delete_index(index_name)
        except Exception:
            # Swallow delete errors and report as best-effort
            pass

        return True
    except Exception as e:
        logger.error(f"clear_model_memories failed: {e}")
        return False
