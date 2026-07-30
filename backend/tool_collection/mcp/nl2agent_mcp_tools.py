"""Implement the internal Local MCP tools used by NL2Agent."""

import logging
import re
import unicodedata
from typing import Any, Literal

from fastmcp.server.dependencies import get_http_request

from agents.nl2agent_agent import (
    Nl2aFewShotExamples,
    SearchInstalledMcpToolsErrorObservation,
    SearchInstalledMcpToolsObservation,
    build_nl2a_wrapper,
)
from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)


def _dump_tool_search_observation(
    observation: SearchInstalledMcpToolsObservation
    | SearchInstalledMcpToolsErrorObservation,
) -> dict[str, Any]:
    """Dump one tool search observation for direct wrapper consumption."""
    return observation.model_dump(mode="json")


def _prepare_search_keywords(keywords: list[str]) -> list[str] | None:
    """Validate and de-duplicate keyword input while preserving its order."""

    if not 1 <= len(keywords) <= 10:
        return None

    prepared_keywords: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        stripped_keyword = keyword.strip()
        if not stripped_keyword or len(stripped_keyword) > 100:
            return None

        normalized_keyword = unicodedata.normalize(
            "NFKC", stripped_keyword
        ).casefold()
        normalized_keyword = re.sub(r"\s+", " ", normalized_keyword)
        if normalized_keyword in seen:
            continue

        seen.add(normalized_keyword)
        prepared_keywords.append(stripped_keyword)

    return prepared_keywords


async def search_installed_mcp_tools(keywords: list[str]) -> dict[str, Any]:
    """Search safe MCP tool metadata for the tenant in the current request."""

    prepared_keywords = _prepare_search_keywords(keywords)
    if prepared_keywords is None:
        return _dump_tool_search_observation(
            SearchInstalledMcpToolsErrorObservation(code="invalid_keywords")
        )

    try:
        # Keep NL2Agent runtime dependencies out of the MCP server startup path.
        from services.nl2agent_service import search_installed_mcp_tools_by_query

        authorization = get_http_request().headers.get("Authorization")
        _, tenant_id = get_current_user_id(authorization)
        recommendations = search_installed_mcp_tools_by_query(
            tenant_id=tenant_id,
            query_text=" ".join(prepared_keywords),
        )
    except Exception:
        logger.exception("Failed to search installed MCP tools from local MCP service")
        return _dump_tool_search_observation(
            SearchInstalledMcpToolsErrorObservation(code="tool_search_failed")
        )

    return _dump_tool_search_observation(
        SearchInstalledMcpToolsObservation(
            recommendation_count=len(recommendations),
            recommendations=recommendations,
        )
    )


async def nl2a_wrapper(
    subtype: Literal["local_mcp_recommendation", "agent_draft"],
    search_result: dict[str, Any] | None = None,
    selected_tool_ids: list[int] | None = None,
    language: Literal["en", "zh"] | None = None,
    name: str | None = None,
    display_name: str | None = None,
    description: str | None = None,
    duty_prompt: str | None = None,
    constraint_prompt: str | None = None,
    greeting_message: str | None = None,
    example_questions: list[str] | None = None,
    selected_tool_names: list[str] | None = None,
    few_shot_examples: Nl2aFewShotExamples | None = None,
) -> str:
    """Return the NL2Agent JSON template selected by subtype in its wrapper."""

    return build_nl2a_wrapper(
        subtype=subtype,
        search_result=search_result,
        selected_tool_ids=selected_tool_ids,
        language=language,
        name=name,
        display_name=display_name,
        description=description,
        duty_prompt=duty_prompt,
        constraint_prompt=constraint_prompt,
        greeting_message=greeting_message,
        example_questions=example_questions,
        selected_tool_names=selected_tool_names,
        few_shot_examples=few_shot_examples,
    )
