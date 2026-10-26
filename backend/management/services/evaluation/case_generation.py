# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
import re
from typing import Any

from contracts.errors.codes import ErrorCode
from contracts.constants.constants import MAX_TURNS_PER_SESSION
from contracts.errors.exceptions import AppException
from management.services.evaluation.common import (
    _QUERY_FORMAT_ERR_MSG,
    logger,
)
from management.services.model.invocation import call_llm_for_system_prompt
from nexent.core.agents.prompt.auxiliary import compose_auxiliary_prompt
from nexent.core.agents.prompt.evaluation import render_evaluation_section


def _build_agent_profile_parts(profile: dict) -> list:
    """Build the agent profile section for the query-generation prompt.

    Conditionally includes each populated profile field so empty fields
    don't pollute the prompt.
    """
    parts = [
        render_evaluation_section(
            "en", "agent_profile_name", {"value": profile["name"]}
        )
    ]
    if profile["description"]:
        parts.append(
            render_evaluation_section(
                "en", "agent_profile_description", {"value": profile["description"]}
            )
        )
    if profile["prompt"]:
        parts.append(
            render_evaluation_section(
                "en", "agent_profile_duty", {"value": profile["prompt"]}
            )
        )
    if profile["business_description"]:
        parts.append(
            render_evaluation_section(
                "en",
                "agent_profile_business",
                {"value": profile["business_description"]},
            )
        )
    return parts


def _extract_cases_from_markdown_fence(response: Any) -> list:
    """Extract a cases list from a markdown-fenced JSON string.

    The LLM occasionally wraps JSON in ```json ... ``` fences; this helper
    peels the fence and parses the inner JSON, raising the standard
    format-error if either step fails.
    """
    match = re.search(r"```(?:json)?\s*(\[.*?])\s*```", response, re.DOTALL)
    if not match:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FORMAT,
            _QUERY_FORMAT_ERR_MSG,
        )
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FORMAT,
            _QUERY_FORMAT_ERR_MSG,
        ) from exc


def _parse_cases_from_llm_response(response: Any) -> list:
    """Parse the LLM response into a list of case dicts.

    Handles three response shapes:
    1. Already a list (passthrough)
    2. JSON string with embedded cases
    3. Markdown-fenced JSON string (e.g. ```json [...] ```)

    Raises ``AppException`` with ``AGENT_EVALUATION_QUERY_GENERATION_FORMAT``
    on any non-list / empty parse result.
    """
    try:
        cases: Any = json.loads(response) if isinstance(response, str) else response
    except json.JSONDecodeError:
        cases = _extract_cases_from_markdown_fence(response)
    if not isinstance(cases, list) or not cases:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FORMAT,
            _QUERY_FORMAT_ERR_MSG,
        )
    return cases


def _generate_test_queries(
    agent_id: int,
    tenant_id: str,
    model_id: int,
    query_count: int = 10,
    language: str = "zh",
) -> list[str]:
    """Generate test queries from agent config via LLM.

    Uses the same template as case generation; extracts only the query strings.
    """
    from management.services.agent.profile import (
        fetch_agent_profile,
    )

    profile = fetch_agent_profile(agent_id, tenant_id)
    if not profile:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_AGENT_NOT_FOUND, f"Agent not found: {agent_id}"
        )

    profile_parts = _build_agent_profile_parts(profile)
    prompt = compose_auxiliary_prompt(
        language,
        "evaluation_cases",
        {
            "profile": "\n".join(profile_parts),
            "count": query_count,
            "max_turns": MAX_TURNS_PER_SESSION,
        },
    )

    try:
        response = call_llm_for_system_prompt(
            model_id=model_id,
            user_prompt=prompt.user,
            system_prompt=prompt.system,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error("LLM call failed for test query generation: %s", exc)
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FAILED, str(exc)
        ) from exc

    cases = _parse_cases_from_llm_response(response)

    # Extract query strings from case objects [{inputs: {query: ...}, label: {answer: ...}}]
    result = [
        str(c.get("inputs", {}).get("query", "")).strip()
        for c in cases
        if isinstance(c, dict)
    ]
    result = [q for q in result if q]
    if not result:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_EMPTY,
            "AI generated no valid test queries",
        )
    logger.info("Generated %d test queries for agent %d", len(result), agent_id)
    return result[:query_count]
