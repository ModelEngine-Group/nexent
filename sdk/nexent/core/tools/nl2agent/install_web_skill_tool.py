"""NL2AGENT tool: install a single official/web skill into the tenant."""

import asyncio
import json
import logging
from typing import Optional

from smolagents import tool

from ._context import (
    Nl2AgentContext,
    error_response,
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
    draft_agent_id: Optional[int] = None,
) -> Nl2AgentContext:
    return set_nl2agent_context(
        agent_id=agent_id,
        draft_agent_id=draft_agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model_id=model_id,
        language=language,
    )


@tool
def nl2agent_install_web_skill(skill_id: int = 0, skill_name: str = "") -> str:
    """Install a single official/web skill into the tenant.

    Use this when the user picks a specific web skill from the recommendation
    list. Each web skill is installed individually — there is no batch install
    for web skills. After install, the skill becomes a local skill and can be
    bound to the draft agent via nl2agent_apply_local_resources.

    Args:
        skill_id: The skill_id of the web skill to install. Use 0 when installing by skill_name.
        skill_name: The official skill name to install when skill_id is missing or 0.

    Returns:
        JSON string with ``skill_id`` and ``installed`` (bool).
    """
    ctx = get_nl2agent_context()
    if ctx is None or ctx.tenant_id is None:
        return error_response("NL2AGENT session context not initialized.")

    try:
        from services.nl2agent_service import install_web_skill as _install

        result = asyncio.run(
            _install(
                skill_id=skill_id,
                skill_name=skill_name or None,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
            )
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception(f"nl2agent_install_web_skill failed: {exc}")
        return error_response(str(exc))
