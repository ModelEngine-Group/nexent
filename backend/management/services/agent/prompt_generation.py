# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
import logging
from typing import Optional

from nexent.core.agents.prompt.auxiliary import compose_auxiliary_prompt

from backend.http.client import create_httpx_client
from contracts.agentos import ChatInvocation, ChatMessage
from contracts.constants.constants import LANGUAGE
from contracts.constants.environment import RUNTIME_SERVICE_URL
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import (
    AppException,
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    RuntimeUpstreamError,
)
from management.clients.agentos import AgentOSClient

logger = logging.getLogger("prompt_service")


def _extract_json_object(raw: str) -> Optional[dict]:
    """Extract the first JSON object from LLM output that may contain markdown fences / surrounding text.

    Fallbacks: markdown fence, surrounding explanation text, single quotes, trailing commas.
    """
    text = (raw or "").strip()
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start:end + 1]
    try:
        return json.loads(snippet)
    except (ValueError, TypeError):
        pass
    # Fallback: single quotes -> double quotes, strip trailing commas
    import re as _re
    try:
        fixed = snippet.replace("'", '"')
        fixed = _re.sub(r",\s*([}\]])", r"\1", fixed)
        return json.loads(fixed)
    except (ValueError, TypeError):
        pass
    # Fallback: LLM often inlines regex escapes (\d \w \s \. etc.) directly into JSON strings.
    # A single backslash is invalid in JSON (only \" \\ \/ \b \f \n \r \t \uXXXX are allowed).
    # Double up backslashes that are not part of a valid JSON escape sequence.
    try:
        fixed = _re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', snippet)
        return json.loads(fixed)
    except (ValueError, TypeError):
        return None


async def generate_guardrail_rules_impl(
    description: str,
    model_id: int,
    tenant_id: str,
    user_id: str,
    language: str = LANGUAGE["ZH"],
) -> dict:
    """Generate guardrail regex rules from a natural-language description via LLM.

    Loads the guardrail prompt template, renders the user prompt with the
    description, calls the LLM, and extracts the JSON object from the (possibly
    malformed) response. Tolerates markdown fences, surrounding prose, single
    quotes, trailing commas, and invalid JSON escapes such as ``\\d`` (LLMs
    often paste regex escapes with a single backslash).

    Args:
        description: Natural-language description of what to match or block.
        model_id: ID of the LLM model used for generation.
        tenant_id: Tenant ID for model resolution and monitoring.
        user_id: Authenticated user initiating generation.
        language: Language code ('zh' or 'en') selecting the prompt template.

    Returns:
        A dict keyed by ``type``:
        - ``{"type": "single", "candidates": [{"pattern": str, "desc": str}]}``
        - ``{"type": "multi", "rules": [{"name": str, "pattern": str,
          "severity": str, "desc": str}]}``

    Raises:
        AppException: If ``description`` is empty, the LLM returns nothing,
            or the response is not valid JSON / carries an unknown ``type``.
    """

    if not (description or "").strip():
        raise AppException(
            ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
            "Description is required.",
        )

    prompt = compose_auxiliary_prompt(language, "guardrail_regex", {"description": description})

    request = ChatInvocation(
        model_id=model_id,
        input=[
            ChatMessage(role="system", content=prompt.system),
            ChatMessage(role="user", content=prompt.user),
        ],
    )
    client = AgentOSClient(RUNTIME_SERVICE_URL, create_httpx_client)
    try:
        result = await client.invoke_model(request, user_id, tenant_id)
    except RuntimeUpstreamError as exc:
        code = ErrorCode.MODEL_NOT_FOUND if exc.status_code == 404 else ErrorCode.MODEL_PROMPT_GENERATION_FAILED
        raise AppException(code) from exc
    except (RuntimeServiceUnavailableError, RuntimeServiceTimeoutError) as exc:
        raise AppException(ErrorCode.MODEL_CONNECTION_ERROR) from exc
    content = result.output.get("content") if isinstance(result.output, dict) else None
    raw = content.strip() if isinstance(content, str) else ""

    # Diagnostic log: record raw LLM output (for troubleshooting "bad format" issues)
    logger.info("[guardrail] desc=%r model_id=%s raw(500)=%s", description[:80], model_id, (raw or "")[:500])

    if not raw:
        raise AppException(ErrorCode.MODEL_PROMPT_GENERATION_FAILED)

    parsed = _extract_json_object(raw)
    if not isinstance(parsed, dict):
        logger.warning("[guardrail] JSON parse failed, raw=%s", (raw or "")[:800])
        raise AppException(
            ErrorCode.MODEL_PROMPT_GENERATION_FAILED,
            "LLM did not return valid JSON for guardrail rules.",
        )

    result_type = str(parsed.get("type") or "").strip().lower()
    if result_type == "single":
        candidates = parsed.get("candidates")
        return {"type": "single", "candidates": candidates if isinstance(candidates, list) else []}
    if result_type == "multi":
        rules = parsed.get("rules")
        return {"type": "multi", "rules": rules if isinstance(rules, list) else []}
    raise AppException(
        ErrorCode.MODEL_PROMPT_GENERATION_FAILED,
        "Unknown guardrail result type.",
    )
