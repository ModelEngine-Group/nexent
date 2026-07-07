"""NL2AGENT tool: search local tools and skills matching the user's intent."""

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


def get_search_local_resources_tool(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    model_id: Optional[int] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
) -> Nl2AgentContext:
    """Initialize the NL2AGENT session context for the nl2agent_search_local_resources tool."""
    return set_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model_id=model_id,
        language=language,
        draft_agent_id=draft_agent_id,
    )


@tool
def nl2agent_search_local_resources(query: str) -> str:
    """Search local tools (SDK + locally-installed MCP + LangChain) and local skills.

    Use this to find resources already available in this tenant that match the
    user's stated goal. Returns a JSON string with two arrays: ``tools`` and
    ``skills``, each containing up to 5 items with fields ``id``, ``name``,
    ``description``, ``source``, ``score`` (0-10), and ``reason``.

    Args:
        query: The user's intent or task description (e.g., "summarize PDFs and email them").

    Returns:
        JSON string ``{"tools": [...], "skills": [...]}``. Tools include a
        ``tool_id`` field; skills include a ``skill_id`` field. Both include a
        ``score`` (0-10) and ``reason``. The frontend renders these as cards
        with an "Apply All" button.
    """
    ctx = get_nl2agent_context()
    if ctx is None or ctx.tenant_id is None:
        return json.dumps(
            {"error": "NL2AGENT session context not initialized."}, ensure_ascii=False
        )
    # nl2agent_search_local_resources scores resources for the draft target. Use
    # draft_agent_id when present; fall back to agent_id (older callers).
    target_agent_id = ctx.draft_agent_id or ctx.agent_id
    if target_agent_id is None:
        return json.dumps(
            {"error": "NL2AGENT draft agent_id not set in context."}, ensure_ascii=False
        )

    try:
        from services.nl2agent_service import recommend_local_resources

        result = asyncio.run(
            recommend_local_resources(
                query=query,
                agent_id=target_agent_id,
                tenant_id=ctx.tenant_id,
                model_id=ctx.model_id or 0,
                top_n=5,
            )
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception(f"nl2agent_search_local_resources failed: {exc}")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
