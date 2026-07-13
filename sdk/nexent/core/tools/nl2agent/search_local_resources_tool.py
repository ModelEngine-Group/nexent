"""NL2AGENT tool: search local tools and skills matching the user's intent."""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from smolagents.tools import Tool

from ._context import (
    Nl2AgentContext,
    _score_candidates,
    create_nl2agent_context,
    error_response,
    get_cached_search,
    set_cached_search,
)


logger = logging.getLogger(__name__)


def _recommendation_batch_id(
    draft_agent_id: Optional[int], query: str, tools: List[Dict[str, Any]], skills: List[Dict[str, Any]]
) -> str:
    """Build a stable opaque ID for one draft/query/result combination."""
    identity = {
        "draft_agent_id": draft_agent_id,
        "query": " ".join(query.lower().split()),
        "tool_ids": sorted(int(item["tool_id"]) for item in tools if item.get("tool_id") is not None),
        "skill_ids": sorted(int(item["skill_id"]) for item in skills if item.get("skill_id") is not None),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
    return f"local_{digest[:24]}"


def get_search_local_resources_tool(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
    tool_catalog: Optional[List[Dict[str, Any]]] = None,
    skill_catalog: Optional[List[Dict[str, Any]]] = None,
) -> Tool:
    context = create_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        draft_agent_id=draft_agent_id,
        tool_catalog=tool_catalog,
        skill_catalog=skill_catalog,
    )
    return NL2AgentSearchLocalResourcesTool(context)


class NL2AgentSearchLocalResourcesTool(Tool):
    """Search local tools (SDK + locally-installed MCP + LangChain) and local skills.

    Use this to find resources already available in this tenant that match the
    user's stated goal. Returns a frontend card JSON string with ``agent_id``,
    ``tools``, and ``skills``. The ``agent_id`` is the draft agent being built.

    Only searches when the query has not been searched before in this session.
    Applied resources from prior searches are preserved in context.

    Args:
        query: Concise search keywords (2-6 words) for one capability,
            e.g. "web search" or "PDF summarization". Never a full sentence.

    Returns:
        JSON string ``{"agent_id": 123, "tools": [...], "skills": [...]}``.
        Tools include a ``tool_id`` field; skills include a ``skill_id`` field.
        Both include a ``score`` (0-1) and ``reason``. The frontend renders
        these as cards with an "Apply All" button.
    """

    name = "nl2agent_search_local_resources"
    description = __doc__ or "Search local tools and skills."
    inputs = {"query": {"type": "string", "description": "Concise search keywords."}}
    output_type = "string"

    def __init__(self, context: Nl2AgentContext):
        super().__init__()
        self.context = context

    def forward(self, query: str) -> str:
        ctx = self.context
        if ctx.tenant_id is None:
            return error_response("NL2AGENT session context not initialized.")
        if ctx.tool_catalog is None or ctx.skill_catalog is None:
            return error_response("tool/skill catalog not available in context")

        q = query.lower().strip()
        cache_key = ("nl2agent_search_local_resources", q)

        if cached := get_cached_search(ctx, *cache_key):
            logger.info(f"nl2agent_search_local_resources cache hit for query: {query}")
            return cached

        # Guard: do not re-search if already searched this session.
        if ctx.was_searched("nl2agent_search_local_resources", query):
            tools = _score_candidates(ctx.tool_catalog, query, "name")[:5]
            skills = _score_candidates(ctx.skill_catalog, query, "name")[:5]
            result = json.dumps(
                {
                    "agent_id": ctx.target_agent_id,
                    "recommendation_batch_id": _recommendation_batch_id(
                        ctx.target_agent_id, query, tools, skills
                    ),
                    "tools": tools,
                    "skills": skills,
                    "already_searched": True,
                    "applied_tool_ids": list(ctx.applied_tool_ids),
                    "applied_skill_ids": list(ctx.applied_skill_ids),
                },
                ensure_ascii=False,
            )
            set_cached_search(ctx, *cache_key, result)
            return result

        tools = _score_candidates(ctx.tool_catalog, query, "name")[:5]
        skills = _score_candidates(ctx.skill_catalog, query, "name")[:5]
        result = json.dumps(
            {
                "agent_id": ctx.target_agent_id,
                "recommendation_batch_id": _recommendation_batch_id(
                    ctx.target_agent_id, query, tools, skills
                ),
                "tools": tools,
                "skills": skills,
            },
            ensure_ascii=False,
        )
        set_cached_search(ctx, *cache_key, result)
        ctx.mark_searched("nl2agent_search_local_resources", query)
        return result
