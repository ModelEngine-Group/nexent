"""NL2AGENT tool: search web MCP marketplaces for individual install."""

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


def get_search_web_mcps_tool(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
    registry_results: Optional[List[Dict[str, Any]]] = None,
    community_results: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    return set_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        draft_agent_id=draft_agent_id,
        registry_results=registry_results,
        community_results=community_results,
    )


@tool
def nl2agent_search_web_mcps(query: str) -> str:
    """Search web MCP marketplaces (official registry + community) for servers matching the user's intent.

    Returns a frontend card JSON string with ``agent_id`` and ``items``. The
    ``agent_id`` is the draft agent being built. Each item has ``name``,
    ``description``, ``source`` ("registry" or "community"), ``url``,
    ``transport``, ``score`` (0-1), and ``reason``. The frontend renders each
    as an individual card with an "Install" button that opens the existing
    AddMcpServiceModal prefilled.

    Only searches when the query has not been searched before in this session.
    Installed MCP servers are tracked in context to avoid re-recommending.

    Args:
        query: 1-3 short keywords matching MCP server names or tags
            (e.g. "github", "email"). Never a full sentence.

    Returns:
        JSON string ``{"agent_id": 123, "items": [...]}`` containing web MCP
        cards.
    """
    ctx = get_nl2agent_context()
    if ctx is None or ctx.tenant_id is None:
        return error_response("NL2AGENT session context not initialized.")
    if ctx.registry_results is None and ctx.community_results is None:
        return error_response("MCP catalog not available in context")

    q = query.lower().strip()
    cache_key = ("nl2agent_search_web_mcps", q)

    if (cached := get_cached_search(*cache_key)):
        logger.info(f"nl2agent_search_web_mcps cache hit for query: {query}")
        return cached

    candidates: List[Dict[str, Any]] = []
    if ctx.registry_results:
        candidates += [{"source": "registry", **r} for r in ctx.registry_results]
    if ctx.community_results:
        candidates += [{"source": "community", **r} for r in ctx.community_results]

    # Guard: if already searched, return cached + applied state
    if ctx.was_searched("nl2agent_search_web_mcps", query):
        scored = _score_candidates(candidates, query, "name")[:5]
        result = json.dumps({
            "agent_id": ctx.target_agent_id,
            "items": scored,
            "already_searched": True,
            "applied_mcp_names": list(ctx.applied_mcp_names),
        }, ensure_ascii=False)
        set_cached_search(*cache_key, result)
        return result

    scored = _score_candidates(candidates, query, "name")[:5]
    result = json.dumps({
        "agent_id": ctx.target_agent_id,
        "items": scored,
    }, ensure_ascii=False)
    set_cached_search(*cache_key, result)
    ctx.mark_searched("nl2agent_search_web_mcps", query)
    return result
