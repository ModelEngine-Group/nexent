"""NL2AGENT tool: search local tools and skills matching the user's intent."""

import hashlib
import json
from typing import Any, Dict, List, Optional

from smolagents.tools import Tool

from ._context import (
    Nl2AgentContext,
    _score_candidates,
    canonical_search_query,
    create_nl2agent_context,
    error_response,
)


def _recommendation_batch_id(
    draft_agent_id: Optional[int], query: str, tools: List[Dict[str, Any]], skills: List[Dict[str, Any]]
) -> str:
    """Build a stable opaque ID for one draft/query/result combination."""
    identity = {
        "draft_agent_id": draft_agent_id,
        "query": canonical_search_query(query),
        "tool_ids": sorted(int(item["tool_id"]) for item in tools if item.get("tool_id") is not None),
        "skill_ids": sorted(int(item["skill_id"]) for item in skills if item.get("skill_id") is not None),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
    return f"local_{digest[:24]}"


def _deduplicate_local_items(
    items: List[Dict[str, Any]], id_field: str, name_field: str = "name"
) -> List[Dict[str, Any]]:
    """Deduplicate one local resource type by stable ID, then normalized name."""
    result: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_names = set()
    for item in items:
        item_id = item.get(id_field)
        normalized_name = canonical_search_query(str(item.get(name_field) or ""))
        is_duplicate = (item_id is not None and item_id in seen_ids) or (
            normalized_name and normalized_name in seen_names
        )
        if item_id is not None:
            seen_ids.add(item_id)
        if normalized_name:
            seen_names.add(normalized_name)
        if is_duplicate:
            continue
        result.append(item)
    return result


def _rank_local_resources(
    context: Nl2AgentContext, query: str
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return at most five tools and skills combined, ordered by relevance."""
    tools = _deduplicate_local_items(
        _score_candidates(context.tool_catalog or [], query, "name"), "tool_id"
    )
    skills = _deduplicate_local_items(
        _score_candidates(context.skill_catalog or [], query, "name"), "skill_id"
    )
    combined = [("tool", item) for item in tools] + [("skill", item) for item in skills]
    combined.sort(
        key=lambda entry: (
            -entry[1].get("score", 0.0),
            0 if entry[0] == "tool" else 1,
            canonical_search_query(str(entry[1].get("name") or "")),
        )
    )
    selected = combined[:5]
    return (
        [item for kind, item in selected if kind == "tool"],
        [item for kind, item in selected if kind == "skill"],
    )


def get_search_local_resources_tool(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
    tool_catalog: Optional[List[Dict[str, Any]]] = None,
    skill_catalog: Optional[List[Dict[str, Any]]] = None,
    requirements_confirmed: bool = False,
) -> Tool:
    context = create_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        draft_agent_id=draft_agent_id,
        tool_catalog=tool_catalog,
        skill_catalog=skill_catalog,
        requirements_confirmed=requirements_confirmed,
    )
    return NL2AgentSearchLocalResourcesTool(context)


class NL2AgentSearchLocalResourcesTool(Tool):
    """Search local tools (SDK + locally-installed MCP + LangChain) and local skills.

    Use this to find resources already available in this tenant that match the
    user's stated goal. Returns a frontend card JSON string with ``agent_id``,
    ``tools``, and ``skills``. The ``agent_id`` is the draft agent being built.

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
        if not ctx.requirements_confirmed:
            return error_response(
                "NL2AGENT requirements are not confirmed for this draft."
            )
        if ctx.tool_catalog is None or ctx.skill_catalog is None:
            return error_response("tool/skill catalog not available in context")

        tools, skills = _rank_local_resources(ctx, query)
        return json.dumps(
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
