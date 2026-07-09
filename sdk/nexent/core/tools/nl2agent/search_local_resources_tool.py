"""NL2AGENT tool: search local tools and skills matching the user's intent."""

import asyncio
import json
import logging
from typing import Optional

from smolagents import tool

from ._context import (
    Nl2AgentContext,
    error_response,
    get_cached_search,
    get_nl2agent_context,
    set_cached_search,
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
    user's stated goal. Returns a frontend card JSON string with ``agent_id``,
    ``tools``, and ``skills``. The ``agent_id`` is the draft agent being built.

    Args:
        query: Concise search keywords (2-6 words) for one capability, e.g. "web search" or "PDF summarization". Never a full sentence.

    Returns:
        JSON string ``{"agent_id": 123, "tools": [...], "skills": [...]}``.
        Tools include a ``tool_id`` field; skills include a ``skill_id`` field.
        Both include a ``score`` (0-10) and ``reason``. The frontend renders
        these as cards with an "Apply All" button.
    """
    ctx = get_nl2agent_context()
    if ctx is None or ctx.tenant_id is None:
        return error_response("NL2AGENT session context not initialized.")

    target = ctx.target_agent_id
    if target is None or target <= 0:
        return error_response("NL2AGENT draft agent_id not set in context.")

    cached_result = get_cached_search("nl2agent_search_local_resources", query)
    if cached_result is not None:
        logger.info(f"nl2agent_search_local_resources cache hit for query: {query}")
        return cached_result

    try:
        from services.nl2agent_service import recommend_local_resources

        result = asyncio.run(
            recommend_local_resources(
                query=query,
                agent_id=target,
                tenant_id=ctx.tenant_id,
                model_id=ctx.model_id,
                top_n=5,
            )
        )
        card_payload = {
            "agent_id": target,
            "tools": result.get("tools", []),
            "skills": result.get("skills", []),
        }
        result_json = json.dumps(card_payload, ensure_ascii=False)
        set_cached_search("nl2agent_search_local_resources", query, result_json)
        return result_json
    except Exception as exc:
        logger.exception(f"nl2agent_search_local_resources failed: {exc}")
        return error_response(str(exc))
