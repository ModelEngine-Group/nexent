"""Shared session context for NL2AGENT builtin tools."""

import json
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# Alias for type-annotation clarity in this module.
_StrStrDict = Dict[str, str]


def error_response(message: str) -> str:
    """Return a consistent JSON error payload used by all NL2AGENT tools."""
    return json.dumps({"error": message}, ensure_ascii=False)


@dataclass
class Nl2AgentContext:
    """Session context for an NL2AGENT tool."""

    agent_id: Optional[int] = None
    draft_agent_id: Optional[int] = None
    tenant_id: Optional[str] = None
    user_id: str = ""
    model_id: int = 0
    language: str = "en"

    @property
    def target_agent_id(self) -> Optional[int]:
        return self.draft_agent_id or self.agent_id


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
        tenant_id=tenant_id,
        user_id=user_id or "",
        model_id=model_id or 0,
        language=language or "en",
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
_search_cache: Dict[
    Tuple[Optional[str], Optional[int], str, str], Tuple[float, str]
] = {}


def _search_cache_key(
    tool_name: str, query: str
) -> Optional[Tuple[Optional[str], Optional[int], str, str]]:
    """Build the cache key for a search call, or None when context is unset."""
    ctx = get_nl2agent_context()
    if ctx is None:
        return None
    return (ctx.tenant_id, ctx.target_agent_id, tool_name, query.strip().lower())


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
    # Evict oldest entries when the cache exceeds the size limit.
    while len(_search_cache) > _SEARCH_CACHE_MAX_ENTRIES:
        # In Python 3.7+ dict maintains insertion order; pop the first (oldest) key.
        _search_cache.pop(next(iter(_search_cache)))
