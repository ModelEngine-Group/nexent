"""NL2AGENT tool: search official/web skills for individual install."""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from smolagents.tools import Tool

from ._context import (
    Nl2AgentContext,
    _score_candidates,
    canonical_search_query,
    create_nl2agent_context,
    error_response,
    get_cached_search,
    set_cached_search,
)


logger = logging.getLogger(__name__)


def _catalog_fingerprint(candidates: List[Dict[str, Any]]) -> str:
    """Return a stable cache namespace for the current Skill catalog snapshot."""
    serialized_items = sorted(
        json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        for item in candidates
    )
    serialized = json.dumps(serialized_items, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def _rank_web_skills(candidates: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Score and deduplicate web skills before applying the result limit."""
    eligible: List[Dict[str, Any]] = []
    for candidate in candidates:
        status = str(candidate.get("status") or "").strip().lower()
        if status != "installable":
            continue
        skill_name = str(candidate.get("skill_name") or candidate.get("name") or "").strip()
        if not skill_name:
            continue
        eligible.append(
            {
                **candidate,
                "skill_name": skill_name,
                "name": str(candidate.get("name") or skill_name),
            }
        )

    scored = _score_candidates(eligible, query, "skill_name")
    result: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_names = set()
    for item in scored:
        skill_id = item.get("skill_id")
        normalized_name = canonical_search_query(
            str(item.get("skill_name") or item.get("name") or "")
        )
        is_duplicate = (skill_id is not None and skill_id in seen_ids) or (
            normalized_name and normalized_name in seen_names
        )
        if skill_id is not None:
            seen_ids.add(skill_id)
        if normalized_name:
            seen_names.add(normalized_name)
        if is_duplicate:
            continue
        result.append(item)
        if len(result) == 5:
            break
    return result


def get_search_web_skills_tool(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
    official_skills: Optional[List[Dict[str, Any]]] = None,
) -> Tool:
    context = create_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        draft_agent_id=draft_agent_id,
        official_skills=official_skills,
    )
    return NL2AgentSearchWebSkillsTool(context)


class NL2AgentSearchWebSkillsTool(Tool):
    """Search the official/web skills marketplace for skills matching the user's intent.

    Returns a frontend card JSON string with ``agent_id`` and ``items``. The
    ``agent_id`` is the draft agent being built. Each item has ``skill_id``,
    ``name``, ``description``, ``tags``, ``score`` (0-1), and ``reason``. The
    frontend renders each as an individual card with an "Install" button.

    Only searches when the query has not been searched before in this session.
    Applied skills are tracked in context to avoid re-recommending.

    Args:
        query: 1-3 short keywords matching skill names or tags
            (e.g. "code review", "document analysis"). Never a full sentence.

    Returns:
        JSON string ``{"agent_id": 123, "items": [...]}`` containing web skill
        cards.
    """

    name = "nl2agent_search_web_skills"
    description = __doc__ or "Search official web skills."
    inputs = {"query": {"type": "string", "description": "Concise skill search keywords."}}
    output_type = "string"

    def __init__(self, context: Nl2AgentContext):
        super().__init__()
        self.context = context

    def forward(self, query: str) -> str:
        ctx = self.context
        if ctx.tenant_id is None:
            return error_response("NL2AGENT session context not initialized.")
        if ctx.official_skills is None:
            return error_response("skills catalog not available in context")

        cache_tool_name = (
            f"nl2agent_search_web_skills:{_catalog_fingerprint(ctx.official_skills)}"
        )
        cache_key = (cache_tool_name, query)

        if cached := get_cached_search(ctx, *cache_key):
            logger.info(f"nl2agent_search_web_skills cache hit for query: {query}")
            return cached

        # Guard: if already searched, return cached + applied state
        if ctx.was_searched(cache_tool_name, query):
            scored = _rank_web_skills(ctx.official_skills, query)
            result = json.dumps(
                {
                    "agent_id": ctx.target_agent_id,
                    "items": scored,
                    "already_searched": True,
                    "applied_skill_ids": list(ctx.applied_skill_ids),
                },
                ensure_ascii=False,
            )
            set_cached_search(ctx, *cache_key, result)
            return result

        scored = _rank_web_skills(ctx.official_skills, query)
        result = json.dumps({"agent_id": ctx.target_agent_id, "items": scored}, ensure_ascii=False)
        set_cached_search(ctx, *cache_key, result)
        ctx.mark_searched(cache_tool_name, query)
        return result
