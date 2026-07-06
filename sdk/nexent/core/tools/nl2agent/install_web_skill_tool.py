"""NL2AGENT tool: install a single official/web skill into the tenant."""

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


def get_install_web_skill_tool(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    model_id: Optional[int] = None,
    language: Optional[str] = None,
) -> Nl2AgentContext:
    """Initialize the NL2AGENT session context for the install_web_skill tool."""
    return set_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model_id=model_id,
        language=language,
    )


@tool
def install_web_skill(skill_id: int) -> str:
    """Install a single official/web skill into the tenant.

    Use this when the user picks a specific web skill from the recommendation
    list. Each web skill is installed individually — there is no batch install
    for web skills. After install, the skill becomes a local skill and can be
    bound to the draft agent via apply_local_resources.

    Args:
        skill_id: The skill_id of the web skill to install.

    Returns:
        JSON string with ``skill_id`` and ``installed`` (bool).
    """
    ctx = get_nl2agent_context()
    if ctx is None or ctx.tenant_id is None:
        return json.dumps(
            {"error": "NL2AGENT session context not initialized."}, ensure_ascii=False
        )

    try:
        from services.nl2agent_service import install_web_skill as _install

        result = asyncio.run(
            _install(
                skill_id=skill_id,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id or "",
            )
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception(f"install_web_skill failed: {exc}")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
