"""Shared tenant-scoped Agent naming rules and LLM regeneration."""

import logging
from typing import Optional

from jinja2 import Template

from consts.const import LANGUAGE
from database.agent_db import query_all_agent_info_by_tenant_id
from utils.llm_utils import call_llm_for_system_prompt
from utils.prompt_template_utils import (
    get_prompt_generate_prompt_template,
    normalize_prompt_generate_template_content,
)

logger = logging.getLogger(__name__)
_NAME_PROMPTS = {
    "name": (
        "agent_name_regenerate",
        "You refine agent variable names so that they stay close to the "
        "original meaning and remain unique within the tenant.",
        "### Task Description:\n{task_description}\n\n"
        "### Original Name:\n{original_value}\n\n"
        "### Existing Names:\n{existing_values}\n\n"
        "Generate a concise Python variable name that keeps the same "
        "meaning and does not duplicate the existing names. Return only "
        "the variable name.",
    ),
    "display_name": (
        "agent_display_name_regenerate",
        "You refine agent display names so they remain unique, concise, "
        "and aligned with the agent's capability.",
        "### Task Description:\n{task_description}\n\n"
        "### Original Display Name:\n{original_value}\n\n"
        "### Existing Display Names:\n{existing_values}\n\n"
        "Generate a new display name that keeps the same meaning but does "
        "not duplicate existing names. Return only the display name.",
    ),
}


def check_agent_value_duplicate(
    field_key: str,
    value: str,
    tenant_id: str,
    exclude_agent_id: int | None = None,
    agents_cache: list[dict] | None = None,
) -> bool:
    """Check either naming field, optionally excluding the edited Agent."""
    if not value:
        return False
    agents = agents_cache if agents_cache is not None else query_all_agent_info_by_tenant_id(tenant_id)
    return any(
        agent.get(field_key) == value
        for agent in agents
        if not exclude_agent_id or agent.get("agent_id") != exclude_agent_id
    )


def generate_unique_agent_value(
    field_key: str,
    base_value: str,
    tenant_id: str,
    agents_cache: list[dict] | None = None,
    exclude_agent_id: int | None = None,
    max_suffix_attempts: int = 100,
) -> str:
    """Find the first free numeric suffix using the existing tenant scope."""
    for counter in range(1, max_suffix_attempts + 1):
        candidate = f"{base_value}_{counter}"
        if not check_agent_value_duplicate(
            field_key, candidate, tenant_id, exclude_agent_id, agents_cache
        ):
            return candidate
    raise ValueError("Failed to generate unique value after max attempts")


def _render_prompt_template(template_str: str, **context) -> str:
    if not template_str:
        return ""
    try:
        return Template(template_str).render(**context).strip()
    except Exception as exc:
        logger.warning("Failed to render prompt template: %s", exc)
        return template_str


def regenerate_agent_value(
    field_key: str,
    original_value: str,
    existing_values: list[str],
    task_description: str,
    model_id: int,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    agents_cache: list[dict] | None = None,
    exclude_agent_id: int | None = None,
    prompt_template_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> str:
    """Regenerate one naming field with five attempts and suffix fallback."""
    prefix, default_system, default_user = _NAME_PROMPTS[field_key]
    if user_id is not None:
        from services.prompt_template_service import resolve_prompt_generate_template

        template = resolve_prompt_generate_template(
            tenant_id=tenant_id, user_id=user_id, language=language,
            prompt_template_id=prompt_template_id,
        )
    else:
        template = normalize_prompt_generate_template_content(
            get_prompt_generate_prompt_template(language)
        )
    values = {value for value in existing_values if value}
    empty_values = "无" if (language or "").lower().startswith(LANGUAGE["ZH"]) else "None"
    context = {
        "task_description": task_description or "",
        "original_value": original_value,
        "existing_values": ", ".join(sorted(values)) if values else empty_values,
    }
    system_prompt = _render_prompt_template(
        template.get(f"{prefix}_system_prompt", ""), original_value=original_value
    ) or default_system
    user_prompt = _render_prompt_template(
        template.get(f"{prefix}_user_prompt", ""), **context
    ) or default_user.format(**context)
    last_error = None
    for attempt in range(1, 6):
        try:
            value = call_llm_for_system_prompt(
                model_id=model_id, user_prompt=user_prompt, system_prompt=system_prompt,
                callback=None, tenant_id=tenant_id,
            )
            candidate = (value or "").strip().splitlines()[0].strip()
            if candidate in values:
                raise ValueError(f"Generated duplicate value '{candidate}'")
            return candidate
        except Exception as exc:
            last_error = exc
            logger.warning("Attempt %s/5 to regenerate value failed: %s", attempt, exc)
    logger.error("Failed to regenerate agent value with LLM after maximum retries", exc_info=last_error)
    return generate_unique_agent_value(
        field_key, original_value, tenant_id, agents_cache, exclude_agent_id
    )
