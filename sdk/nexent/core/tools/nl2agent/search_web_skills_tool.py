"""NL2AGENT tool: search official/web skills for individual install."""

import json
import logging
from typing import Any, Dict, List, Optional

from smolagents import tool

from ._context import (
    _score_candidates,
    error_response,
    get_cached_search,
    get_nl2agent_context,
    set_cached_search,
    set_nl2agent_context,
)

logger = logging.getLogger(__name__)


def get_search_web_skills_tool(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
    official_skills: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    return set_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        draft_agent_id=draft_agent_id,
        official_skills=official_skills,
    )


@tool
def nl2agent_search_web_skills(query: str) -> str:
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
    ctx = get_nl2agent_context()
    if ctx is None or ctx.tenant_id is None:
        return error_response("NL2AGENT session context not initialized.")
    if ctx.official_skills is None:
        return error_response("skills catalog not available in context")

    q = query.lower().strip()
    cache_key = ("nl2agent_search_web_skills", q)

    if (cached := get_cached_search(*cache_key)):
        logger.info(f"nl2agent_search_web_skills cache hit for query: {query}")
        return cached

    # Guard: if already searched, return cached + applied state
    if ctx.was_searched("nl2agent_search_web_skills", query):
        scored = _score_candidates(ctx.official_skills, query, "skill_name")[:5]
        result = json.dumps({
            "agent_id": ctx.target_agent_id,
            "items": scored,
            "already_searched": True,
            "applied_skill_ids": list(ctx.applied_skill_ids),
        }, ensure_ascii=False)
        set_cached_search(*cache_key, result)
        return result

    scored = _score_candidates(ctx.official_skills, query, "skill_name")[:5]
    result = json.dumps({
        "agent_id": ctx.target_agent_id,
        "items": scored,
    }, ensure_ascii=False)
    set_cached_search(*cache_key, result)
    ctx.mark_searched("nl2agent_search_web_skills", query)
    return result
