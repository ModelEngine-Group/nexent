"""Shared session context for NL2AGENT builtin tools.

Each NL2AGENT tool reads its session context (draft agent_id, user_id,
tenant_id, model_id, language) from this module. The context is injected at
agent build time via `ToolConfig.metadata` and set by `get_*_tool()` in each
tool module.

This mirrors the pattern in `read_skill_config_tool.py` where a module-level
global holds the tool instance.
"""

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class Nl2AgentContext:
    """Session context for an NL2AGENT tool.

    Attributes:
        agent_id: The running NL2AGENT default agent's id (the chat agent).
        draft_agent_id: The target draft agent being built. Tools that operate
            on the draft (nl2agent_apply_local_resources,
            nl2agent_finalize_agent, nl2agent_search_local_resources) read this
            field. Falls back to agent_id
            when not set (backward-compat).
        user_id: The user initiating the session.
        tenant_id: The tenant ID.
        model_id: The model ID used for LLM scoring.
        language: The language code ("zh" or "en").
    """
    agent_id: Optional[int] = None
    draft_agent_id: Optional[int] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    model_id: Optional[int] = None
    language: Optional[str] = None


# Module-level context singleton. Set by the `get_*_tool()` initializers.
_context: Optional[Nl2AgentContext] = None


def set_nl2agent_context(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    model_id: Optional[int] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
) -> Nl2AgentContext:
    """Set the global NL2AGENT session context. Idempotent; overwrites prior values."""
    global _context
    _context = Nl2AgentContext(
        agent_id=agent_id,
        draft_agent_id=draft_agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model_id=model_id,
        language=language,
    )
    return _context


def get_nl2agent_context() -> Optional[Nl2AgentContext]:
    """Return the current NL2AGENT session context, or None if not set."""
    return _context


# Cache for search tool results. Module-level (not a field on the dataclass)
# because set_nl2agent_context() runs on every agent build, which happens once
# per chat message; cache entries must survive those resets to deduplicate
# searches across turns. Keys include tenant and target agent ids so
# concurrent sessions never read each other's results.
_SEARCH_CACHE_TTL_SECONDS = 600.0
_SEARCH_CACHE_MAX_ENTRIES = 128
_search_cache: "OrderedDict[Tuple[Optional[str], Optional[int], str, str], Tuple[float, str]]" = OrderedDict()


def _search_cache_key(
    tool_name: str, query: str
) -> Optional[Tuple[Optional[str], Optional[int], str, str]]:
    """Build the cache key for a search call, or None when context is unset."""
    ctx = get_nl2agent_context()
    if ctx is None:
        return None
    target_agent_id = ctx.draft_agent_id or ctx.agent_id
    return (ctx.tenant_id, target_agent_id, tool_name, query.strip().lower())


def get_cached_search(tool_name: str, query: str) -> Optional[str]:
    """Return the cached result for this search, or None on miss or expiry."""
    key = _search_cache_key(tool_name, query)
    if key is None:
        return None
    entry = _search_cache.get(key)
    if entry is None:
        return None
    cached_at, result = entry
    if time.monotonic() - cached_at > _SEARCH_CACHE_TTL_SECONDS:
        _search_cache.pop(key, None)
        return None
    return result


def set_cached_search(tool_name: str, query: str, result: str) -> None:
    """Cache a successful search result for the current session context."""
    key = _search_cache_key(tool_name, query)
    if key is None:
        return
    _search_cache[key] = (time.monotonic(), result)
    _search_cache.move_to_end(key)
    while len(_search_cache) > _SEARCH_CACHE_MAX_ENTRIES:
        _search_cache.popitem(last=False)
