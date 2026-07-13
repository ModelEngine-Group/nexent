"""Shared session context for NL2AGENT builtin tools."""

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# Alias for type-annotation clarity in this module.
_StrStrDict = Dict[str, str]

_SEARCH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "of",
    "or",
    "the",
    "to",
    "tool",
    "tools",
    "use",
    "using",
    "with",
    "以及",
    "使用",
    "和",
    "实现",
    "工具",
    "技能",
    "用于",
    "的",
    "通过",
    "与",
}
_SEARCH_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff]+")
_MIN_KEYWORD_SCORE = 0.62


def error_response(message: str) -> str:
    """Return a consistent JSON error payload used by all NL2AGENT tools."""
    return json.dumps({"error": message}, ensure_ascii=False)


def normalize_search_keywords(query: str) -> List[str]:
    """Normalize a search query into distinct atomic Latin or CJK keywords."""
    normalized = unicodedata.normalize("NFKC", str(query or "")).casefold()
    keywords: List[str] = []
    seen: Set[str] = set()
    for match in _SEARCH_TOKEN_PATTERN.finditer(normalized):
        keyword = match.group(0)
        if not keyword or keyword in _SEARCH_STOP_WORDS or keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword)
    return keywords


def canonical_search_query(query: str) -> str:
    """Return an order-independent signature for an equivalent keyword set."""
    return "\x1f".join(sorted(normalize_search_keywords(query)))


def _searchable_text(value: Any) -> str:
    """Flatten catalog metadata into normalized searchable text."""
    if value is None:
        return ""
    if isinstance(value, dict):
        value = " ".join(f"{key} {_searchable_text(item)}" for key, item in value.items())
    elif isinstance(value, (list, tuple, set)):
        value = " ".join(_searchable_text(item) for item in value)
    return unicodedata.normalize("NFKC", str(value)).casefold()


def _keyword_similarity(keyword: str, text: str) -> float:
    """Score one keyword against one catalog field."""
    if not text:
        return 0.0
    if keyword in text:
        return 1.0
    # Very short fuzzy matches are noisy (for example, "ppt" vs "http").
    if len(keyword) <= 3:
        return 0.0
    try:
        from rapidfuzz import fuzz

        return fuzz.partial_ratio(keyword, text) / 100.0
    except ImportError:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, keyword, text).ratio()


def _score_candidates(
    candidates: List[Dict[str, Any]],
    query: str,
    name_field: str,
    score_field: str = "score",
) -> List[Dict[str, Any]]:
    """Fuzzy-match each normalized keyword independently with OR semantics."""
    keywords = normalize_search_keywords(query)
    if not keywords:
        return []

    scored: List[Dict[str, Any]] = []
    for candidate in candidates:
        name = _searchable_text(candidate.get(name_field, ""))
        metadata = " ".join(
            _searchable_text(candidate.get(field)) for field in ("description", "tags")
        )
        matches: List[Tuple[str, float]] = []
        for keyword in keywords:
            name_score = _keyword_similarity(keyword, name)
            metadata_score = 0.9 * _keyword_similarity(keyword, metadata)
            keyword_score = max(name_score, metadata_score)
            if keyword_score >= _MIN_KEYWORD_SCORE:
                matches.append((keyword, keyword_score))

        if not matches:
            continue
        best_score = max(score for _, score in matches)
        coverage = len(matches) / len(keywords)
        composite = 0.85 * best_score + 0.15 * coverage
        matched_keywords = ", ".join(keyword for keyword, _ in matches)
        scored.append(
            {
                **candidate,
                score_field: round(composite, 4),
                "reason": f"Matched keywords: {matched_keywords}",
            }
        )
    scored.sort(
        key=lambda item: (
            -item[score_field],
            _searchable_text(item.get(name_field, "")),
        )
    )
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
        self._searched_queries.setdefault(tool_name, set()).add(canonical_search_query(query))

    def was_searched(self, tool_name: str, query: str) -> bool:
        return canonical_search_query(query) in self._searched_queries.get(tool_name, set())

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
        canonical_search_query(query),
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
