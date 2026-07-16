"""Shared session context for NL2AGENT builtin tools."""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
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


def online_recommendation_batch_id(
    draft_agent_id: Optional[int],
    resource_type: str,
    query: str,
    item_keys: List[str],
) -> str:
    """Build a stable identifier for one online recommendation result batch."""
    payload = {
        "draft_agent_id": int(draft_agent_id or 0),
        "resource_type": resource_type,
        "query": canonical_search_query(query),
        "item_keys": sorted({str(key) for key in item_keys if str(key)}),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"online_{digest}"


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
    requirements_confirmed: bool = False

    # Pre-fetched catalogs injected by backend (all optional — tools guard on None)
    tool_catalog: Optional[List[Dict[str, Any]]] = None
    skill_catalog: Optional[List[Dict[str, Any]]] = None
    registry_results: Optional[List[Dict[str, Any]]] = None
    community_results: Optional[List[Dict[str, Any]]] = None
    official_skills: Optional[List[Dict[str, Any]]] = None

    @property
    def target_agent_id(self) -> Optional[int]:
        return self.draft_agent_id or self.agent_id


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
    requirements_confirmed: bool = False,
) -> Nl2AgentContext:
    """Create isolated context for one NL2AGENT tool instance."""
    return Nl2AgentContext(
        agent_id=agent_id,
        draft_agent_id=draft_agent_id,
        tenant_id=tenant_id,
        user_id=user_id or "",
        language=language or "en",
        requirements_confirmed=bool(requirements_confirmed),
        tool_catalog=tool_catalog,
        skill_catalog=skill_catalog,
        registry_results=registry_results,
        community_results=community_results,
        official_skills=official_skills,
    )

