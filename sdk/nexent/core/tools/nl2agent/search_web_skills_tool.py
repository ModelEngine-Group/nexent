"""NL2AGENT tool: search official/web skills for individual install."""

import json
from typing import Any, Dict, List, Optional

from smolagents.tools import Tool

from ._context import (
    Nl2AgentContext,
    _score_candidates,
    canonical_search_query,
    create_nl2agent_context,
    error_response,
    online_recommendation_batch_id,
)


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
    requirements_confirmed: bool = False,
) -> Tool:
    context = create_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        draft_agent_id=draft_agent_id,
        official_skills=official_skills,
        requirements_confirmed=requirements_confirmed,
    )
    return NL2AgentSearchWebSkillsTool(context)


class NL2AgentSearchWebSkillsTool(Tool):
    """Search the official/web skills marketplace for skills matching the user's intent.

    Returns a frontend card JSON string with ``agent_id`` and ``items``. The
    ``agent_id`` is the draft agent being built. Each item has ``skill_id``,
    ``name``, ``description``, ``tags``, ``score`` (0-1), and ``reason``. The
    frontend renders each as an individual card with an "Install" button.

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
        if not ctx.requirements_confirmed:
            return error_response(
                "NL2AGENT requirements are not confirmed for this draft."
            )
        if ctx.official_skills is None:
            return error_response("skills catalog not available in context")

        scored = _rank_web_skills(ctx.official_skills, query)
        item_keys = [
            f"skill:{item.get('skill_id')}"
            if item.get("skill_id")
            else f"skill-name:{canonical_search_query(str(item.get('skill_name') or item.get('name') or ''))}"
            for item in scored
        ]
        return json.dumps(
            {
                "agent_id": ctx.target_agent_id,
                "recommendation_batch_id": online_recommendation_batch_id(
                    ctx.target_agent_id, "skill", query, item_keys
                ),
                "items": scored,
            },
            ensure_ascii=False,
        )
