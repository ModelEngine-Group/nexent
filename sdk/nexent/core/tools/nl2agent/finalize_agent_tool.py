"""NL2AGENT tool: finalize the draft agent by generating its full prompt set."""

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


def get_finalize_agent_tool(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    model_id: Optional[int] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
) -> Nl2AgentContext:
    """Initialize the NL2AGENT session context for the nl2agent_finalize_agent tool."""
    return set_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model_id=model_id,
        language=language,
        draft_agent_id=draft_agent_id,
    )


@tool
def nl2agent_finalize_agent(
    task_description: str,
    tool_ids: str,
    skill_ids: str = "[]",
    sub_agent_ids: str = "[]",
    knowledge_base_names: str = "[]",
) -> str:
    """Finalize the draft agent by generating its full prompt set.

    Call this when the user confirms they're done and the agent has gathered
    enough information. This generates the duty, constraint, few_shots,
    greeting, example questions, name, display_name, and description for the
    draft agent and persists them. After this, the draft is ready for the user
    to review and publish.

    Args:
        task_description: A clear summary of what the agent should do, synthesized from the conversation.
        tool_ids: JSON-encoded list of tool IDs bound to the agent, e.g. "[1, 2]".
        skill_ids: JSON-encoded list of skill IDs bound to the agent. Defaults to "[]".
        sub_agent_ids: JSON-encoded list of sub-agent IDs. Defaults to "[]".
        knowledge_base_names: JSON-encoded list of knowledge base display names. Defaults to "[]".

    Returns:
        JSON string with ``agent_id`` and ``status`` ("draft_ready").
    """
    ctx = get_nl2agent_context()
    if ctx is None or ctx.tenant_id is None:
        return json.dumps(
            {"error": "NL2AGENT session context not initialized."}, ensure_ascii=False
        )
    # nl2agent_finalize_agent writes generated prompts to the draft target. Use
    # draft_agent_id when present; fall back to agent_id (older callers).
    target_agent_id = ctx.draft_agent_id or ctx.agent_id
    if target_agent_id is None:
        return json.dumps(
            {"error": "NL2AGENT draft agent_id not set in context."}, ensure_ascii=False
        )

    try:
        parsed_tool_ids = json.loads(tool_ids) if tool_ids else []
        parsed_skill_ids = json.loads(skill_ids) if skill_ids else []
        parsed_sub_agent_ids = json.loads(sub_agent_ids) if sub_agent_ids else []
        parsed_kb_names = json.loads(knowledge_base_names) if knowledge_base_names else []
    except json.JSONDecodeError as exc:
        return json.dumps(
            {"error": f"Invalid JSON list argument: {exc}"}, ensure_ascii=False
        )

    try:
        from services.nl2agent_service import finalize_agent as _finalize

        result = asyncio.run(
            _finalize(
                agent_id=target_agent_id,
                model_id=ctx.model_id or 0,
                task_description=task_description,
                tool_ids=parsed_tool_ids,
                skill_ids=parsed_skill_ids,
                sub_agent_ids=parsed_sub_agent_ids,
                knowledge_base_display_names=parsed_kb_names,
                user_id=ctx.user_id or "",
                tenant_id=ctx.tenant_id,
                language=ctx.language or "en",
            )
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception(f"nl2agent_finalize_agent failed: {exc}")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
