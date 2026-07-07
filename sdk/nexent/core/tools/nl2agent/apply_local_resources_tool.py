"""NL2AGENT tool: bulk-apply local tools and skills ("Apply All")."""

import asyncio
import json
import logging
from typing import Optional

from smolagents import tool

from nexent.core.tools.nl2agent._context import (
    Nl2AgentContext,
    get_nl2agent_context,
    set_nl2agent_context,
)

logger = logging.getLogger(__name__)


def get_apply_local_resources_tool(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    model_id: Optional[int] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
) -> Nl2AgentContext:
    """Initialize the NL2AGENT session context for the apply_local_resources tool."""
    return set_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model_id=model_id,
        language=language,
        draft_agent_id=draft_agent_id,
    )


@tool
def apply_local_resources(tool_ids: str, skill_ids: str) -> str:
    """Bind the selected local tools and skills to the draft agent in one batch.

    Call this after the user confirms which recommended local tools and skills
    to use. This is the "Apply All" action: it binds every listed tool_id and
    skill_id to the draft agent being built.

    Args:
        tool_ids: JSON-encoded list of tool IDs (integers) to bind, e.g. "[1, 2, 3]". Use "[]" if none.
        skill_ids: JSON-encoded list of skill IDs (integers) to bind, e.g. "[10, 11]". Use "[]" if none.

    Returns:
        JSON string with ``bound_tool_count`` and ``bound_skill_count``.
    """
    ctx = get_nl2agent_context()
    if ctx is None or ctx.tenant_id is None:
        return json.dumps(
            {"error": "NL2AGENT session context not initialized."}, ensure_ascii=False
        )
    # apply_local_resources binds resources to the draft target. Use
    # draft_agent_id when present; fall back to agent_id (older callers).
    target_agent_id = ctx.draft_agent_id or ctx.agent_id
    if target_agent_id is None:
        return json.dumps(
            {"error": "NL2AGENT draft agent_id not set in context."}, ensure_ascii=False
        )

    try:
        parsed_tool_ids = json.loads(tool_ids) if tool_ids else []
        parsed_skill_ids = json.loads(skill_ids) if skill_ids else []
    except json.JSONDecodeError as exc:
        return json.dumps(
            {"error": f"Invalid JSON list for tool_ids/skill_ids: {exc}"},
            ensure_ascii=False,
        )

    try:
        from services.nl2agent_service import apply_local_resources_batch

        result = asyncio.run(
            apply_local_resources_batch(
                agent_id=target_agent_id,
                tool_ids=parsed_tool_ids,
                skill_ids=parsed_skill_ids,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id or "",
            )
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception(f"apply_local_resources failed: {exc}")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
