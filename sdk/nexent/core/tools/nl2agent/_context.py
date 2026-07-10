"""Shared session context for NL2AGENT builtin tools."""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

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
    language: str = "en"

    # ── Applied resources state (survive across turns) ───────────────────────
    # Set when the user clicks "Apply All" on LocalResourcesCard or when the
    # frontend saves tool/skill configs via ToolConfigModal.
    applied_tool_ids: Set[int] = field(default_factory=set)
    applied_skill_ids: Set[int] = field(default_factory=set)
    applied_mcp_names: Set[str] = field(default_factory=set)  # MCP server names
    applied_sub_agent_ids: Set[int] = field(default_factory=set)

    # Per-resource config overrides set during the session.
    # tool_id -> {param_name: value}  (e.g. MCP server_url, api_key)
    tool_configs: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    # skill_id -> {config_key: value}
    skill_configs: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # Tracks which (tool_name, query) combos have been searched this session
    # so the agent knows "never searched before" vs "already searched".
    _searched_queries: Dict[str, Set[str]] = field(default_factory=dict)

    @property
    def target_agent_id(self) -> Optional[int]:
        return self.draft_agent_id or self.agent_id

    # ── Convenience helpers ─────────────────────────────────────────────────

    def has_applied_tool(self, tool_id: int) -> bool:
        """Return True if this tool has been applied in the session."""
        return tool_id in self.applied_tool_ids

    def has_applied_skill(self, skill_id: int) -> bool:
        """Return True if this skill has been applied in the session."""
        return skill_id in self.applied_skill_ids

    def has_applied_mcp(self, mcp_name: str) -> bool:
        """Return True if this MCP server has been installed in the session."""
        return mcp_name in self.applied_mcp_names

    def mark_tool_applied(
        self, tool_id: int, params: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record that a tool has been applied, optionally with config overrides."""
        self.applied_tool_ids.add(tool_id)
        if params:
            self.tool_configs[tool_id] = params

    def mark_skill_applied(
        self, skill_id: int, config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record that a skill has been applied, optionally with config overrides."""
        self.applied_skill_ids.add(skill_id)
        if config:
            self.skill_configs[skill_id] = config

    def mark_mcp_applied(self, mcp_name: str) -> None:
        """Record that an MCP server has been installed in the session."""
        self.applied_mcp_names.add(mcp_name)

    def mark_searched(self, tool_name: str, query: str) -> None:
        """Record that a search tool was called with this query this session."""
        q = query.strip().lower()
        self._searched_queries.setdefault(tool_name, set()).add(q)

    def was_searched(self, tool_name: str, query: str) -> bool:
        """Return True if this search tool was already called with this query."""
        return query.strip().lower() in self._searched_queries.get(tool_name, set())

    def get_tool_config(self, tool_id: int) -> Dict[str, Any]:
        """Return the saved config overrides for a tool, or an empty dict."""
        return self.tool_configs.get(tool_id, {})

    def get_skill_config(self, skill_id: int) -> Dict[str, Any]:
        """Return the saved config overrides for a skill, or an empty dict."""
        return self.skill_configs.get(skill_id, {})

    def get_all_applied_tool_ids(self) -> List[int]:
        """Return sorted list of all applied tool IDs."""
        return sorted(self.applied_tool_ids)

    def get_all_applied_skill_ids(self) -> List[int]:
        """Return sorted list of all applied skill IDs."""
        return sorted(self.applied_skill_ids)


# Module-level context singleton. Set by the `get_*_tool()` initializers.
_context: Optional[Nl2AgentContext] = None


def set_nl2agent_context(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
) -> Nl2AgentContext:
    """Set the global NL2AGENT session context. Idempotent; overwrites prior values.

    Applied resources state (applied_tool_ids, applied_skill_ids, tool_configs,
    skill_configs, _searched_queries) is reset on each call so the context always
    starts fresh for a new conversation turn.
    """
    global _context
    _context = Nl2AgentContext(
        agent_id=agent_id,
        draft_agent_id=draft_agent_id,
        tenant_id=tenant_id,
        user_id=user_id or "",
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
