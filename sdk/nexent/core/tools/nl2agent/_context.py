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


def _score_candidates(
    candidates: List[Dict[str, Any]],
    query: str,
    name_field: str,
    score_field: str = "score",
) -> List[Dict[str, Any]]:
    """Relevance scoring via fuzzy string matching over name + description.

    Combines three signals:
    1. Token-overlap score: fraction of query words found in name + description.
    2. Substring containment bonus: +0.3 if the full query appears as a substring in name.
    3. Edit-distance fuzzy score: rapidfuzz.partial_ratio (or difflib fallback).

    Blended: 40% token-overlap + 30% substring + 30% fuzzy.
    rapidfuzz is an optional dependency (add to sdk/pyproject.toml);
    difflib is the zero-dependency fallback.
    """
    query_lower = query.lower()
    query_words = query_lower.split()
    scored = []
    for c in candidates:
        name = c.get(name_field, "").lower()
        description = c.get("description", "").lower()
        combined = name + " " + description

        # Signal 1: token-overlap
        overlap = sum(1 for w in query_words if w in combined) / max(len(query_words), 1)

        # Signal 2: substring containment bonus
        substring_bonus = 0.3 if query_lower in name else 0.0

        # Signal 3: fuzzy match
        try:
            from rapidfuzz import fuzz

            fuzzy_score = fuzz.partial_ratio(query_lower, combined) / 100.0
        except ImportError:
            from difflib import SequenceMatcher

            fuzzy_score = SequenceMatcher(None, query_lower, combined).ratio()

        # Blend
        composite = 0.4 * overlap + 0.3 * substring_bonus + 0.3 * fuzzy_score
        scored.append({**c, score_field: round(composite, 4), "reason": ""})
    scored.sort(key=lambda x: x[score_field], reverse=True)
    return scored


@dataclass
class Nl2AgentContext:
    """Session context for an NL2AGENT tool."""

    agent_id: Optional[int] = None
    draft_agent_id: Optional[int] = None
    tenant_id: Optional[str] = None
    user_id: str = ""
    language: str = "en"

    # Pre-fetched catalogs injected by backend (all optional — tools guard on None)
    tool_catalog: Optional[List[Dict[str, Any]]] = None
    skill_catalog: Optional[List[Dict[str, Any]]] = None
    registry_results: Optional[List[Dict[str, Any]]] = None
    community_results: Optional[List[Dict[str, Any]]] = None
    official_skills: Optional[List[Dict[str, Any]]] = None

    # Applied resources state (survive across turns)
    applied_tool_ids: Set[int] = field(default_factory=set)
    applied_skill_ids: Set[int] = field(default_factory=set)
    applied_mcp_names: Set[str] = field(default_factory=set)
    applied_sub_agent_ids: Set[int] = field(default_factory=set)

    # Per-resource config overrides set during the session.
    tool_configs: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    skill_configs: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # Tracks which (tool_name, query) combos have been searched this session.
    _searched_queries: Dict[str, Set[str]] = field(default_factory=dict)

    @property
    def target_agent_id(self) -> Optional[int]:
        return self.draft_agent_id or self.agent_id

    # ── Convenience helpers ─────────────────────────────────────────────────

    def has_applied_tool(self, tool_id: int) -> bool:
        return tool_id in self.applied_tool_ids

    def has_applied_skill(self, skill_id: int) -> bool:
        return skill_id in self.applied_skill_ids

    def has_applied_mcp(self, mcp_name: str) -> bool:
        return mcp_name in self.applied_mcp_names

    def mark_tool_applied(self, tool_id: int, params: Optional[Dict[str, Any]] = None) -> None:
        self.applied_tool_ids.add(tool_id)
        if params:
            self.tool_configs[tool_id] = params

    def mark_skill_applied(self, skill_id: int, config: Optional[Dict[str, Any]] = None) -> None:
        self.applied_skill_ids.add(skill_id)
        if config:
            self.skill_configs[skill_id] = config

    def mark_mcp_applied(self, mcp_name: str) -> None:
        self.applied_mcp_names.add(mcp_name)

    def mark_searched(self, tool_name: str, query: str) -> None:
        self._searched_queries.setdefault(tool_name, set()).add(query.strip().lower())

    def was_searched(self, tool_name: str, query: str) -> bool:
        return query.strip().lower() in self._searched_queries.get(tool_name, set())

    def get_tool_config(self, tool_id: int) -> Dict[str, Any]:
        return self.tool_configs.get(tool_id, {})

    def get_skill_config(self, skill_id: int) -> Dict[str, Any]:
        return self.skill_configs.get(skill_id, {})

    def get_all_applied_tool_ids(self) -> List[int]:
        return sorted(self.applied_tool_ids)

    def get_all_applied_skill_ids(self) -> List[int]:
        return sorted(self.applied_skill_ids)


def create_nl2agent_context(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
    tool_catalog: Optional[List[Dict[str, Any]]] = None,
    skill_catalog: Optional[List[Dict[str, Any]]] = None,
    registry_results: Optional[List[Dict[str, Any]]] = None,
    community_results: Optional[List[Dict[str, Any]]] = None,
    official_skills: Optional[List[Dict[str, Any]]] = None,
) -> Nl2AgentContext:
    """Create isolated context for one NL2AGENT tool instance."""
    return Nl2AgentContext(
        agent_id=agent_id,
        draft_agent_id=draft_agent_id,
        tenant_id=tenant_id,
        user_id=user_id or "",
        language=language or "en",
        tool_catalog=tool_catalog,
        skill_catalog=skill_catalog,
        registry_results=registry_results,
        community_results=community_results,
        official_skills=official_skills,
    )


# Cache for search tool results. Module-level (not a field on the dataclass)
# so entries survive agent rebuilds across chat turns. Every operation receives
# its owning context explicitly; tool instances never depend on mutable global
# session state.
_SEARCH_CACHE_TTL_SECONDS = 600.0
_SEARCH_CACHE_MAX_ENTRIES = 128
_search_cache: Dict[Tuple[Optional[str], Optional[int], str, str], Tuple[float, str]] = {}


def _search_cache_key(
    context: Nl2AgentContext, tool_name: str, query: str
) -> Optional[Tuple[Optional[str], Optional[int], str, str]]:
    """Build a cache key scoped to the tool instance's session context."""
    return (
        context.tenant_id,
        context.target_agent_id,
        tool_name,
        query.strip().lower(),
    )


def get_cached_search(context: Nl2AgentContext, tool_name: str, query: str) -> Optional[str]:
    """Return the cached result for this search, or None on miss or expiry."""
    key = _search_cache_key(context, tool_name, query)
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


def set_cached_search(context: Nl2AgentContext, tool_name: str, query: str, result: str) -> None:
    """Cache a successful search result for the current session context."""
    key = _search_cache_key(context, tool_name, query)
    if key is None:
        return
    _search_cache[key] = (time.monotonic(), result)
    while len(_search_cache) > _SEARCH_CACHE_MAX_ENTRIES:
        _search_cache.pop(next(iter(_search_cache)))
