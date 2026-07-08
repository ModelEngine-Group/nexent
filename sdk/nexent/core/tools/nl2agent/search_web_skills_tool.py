"""NL2AGENT tool: search official/web skills for individual install."""

import asyncio
import json
import logging
from typing import Optional

from smolagents import tool

from ._context import (
    Nl2AgentContext,
    get_nl2agent_context,
    set_nl2agent_context,
)

logger = logging.getLogger(__name__)


def get_search_web_skills_tool(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    model_id: Optional[int] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
) -> Nl2AgentContext:
    """Initialize the NL2AGENT session context for the nl2agent_search_web_skills tool."""
    return set_nl2agent_context(
        agent_id=agent_id,
        draft_agent_id=draft_agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model_id=model_id,
        language=language,
    )


@tool
def nl2agent_search_web_skills(query: str) -> str:
    """Search the official/web skills marketplace for skills matching the user's intent.

    Returns a frontend card JSON string with ``agent_id`` and ``items``. The
    ``agent_id`` is the draft agent being built. Each item has ``skill_id``,
    ``name``, ``description``, ``tags``, ``score`` (0-10), and ``reason``. The
    frontend renders each as an individual card with an "Install" button.

    Args:
        query: The user's intent or task description.

    Returns:
        JSON string ``{"agent_id": 123, "items": [...]}`` containing web skill
        cards.
    """
    ctx = get_nl2agent_context()
    if ctx is None or ctx.tenant_id is None:
        return json.dumps(
            {"error": "NL2AGENT session context not initialized."}, ensure_ascii=False
        )
    target_agent_id = ctx.draft_agent_id or ctx.agent_id
    if target_agent_id is None or target_agent_id <= 0:
        return json.dumps(
            {"error": "NL2AGENT draft agent_id not set in context."}, ensure_ascii=False
        )

    try:
        from services.nl2agent_service import search_web_skills as _search

        items = asyncio.run(
            _search(
                query=query,
                tenant_id=ctx.tenant_id,
                model_id=ctx.model_id or 0,
                top_n=5,
            )
        )
        return json.dumps(
            {"agent_id": target_agent_id, "items": items or []},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception(f"nl2agent_search_web_skills failed: {exc}")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
