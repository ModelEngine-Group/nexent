"""NL2AGENT tool: bulk-apply local tools and skills ("Apply All")."""

import asyncio
import json
import logging
from typing import List, Optional

from smolagents import tool

from ._context import (
    Nl2AgentContext,
    error_response,
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
    return set_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model_id=model_id,
        language=language,
        draft_agent_id=draft_agent_id,
    )


def _parse_json_list(value: str) -> List:
    """Parse a JSON-encoded list, returning [] for empty/falsy input."""
    if not value:
        return []
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON list argument: {exc}") from exc


@tool
def nl2agent_apply_local_resources(tool_ids: str, skill_ids: str) -> str:
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
        return error_response("NL2AGENT session context not initialized.")

    target = ctx.target_agent_id
    if target is None or target <= 0:
        return error_response("NL2AGENT draft agent_id not set in context.")

    try:
        parsed_tool_ids = _parse_json_list(tool_ids)
        parsed_skill_ids = _parse_json_list(skill_ids)
    except ValueError as exc:
        return error_response(str(exc))

    try:
        from services.nl2agent_service import apply_local_resources_batch

        result = asyncio.run(
            apply_local_resources_batch(
                agent_id=target,
                tool_ids=parsed_tool_ids,
                skill_ids=parsed_skill_ids,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
            )
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception(f"nl2agent_apply_local_resources failed: {exc}")
        return error_response(str(exc))
