"""Shared tenant-scoped Agent naming rules and LLM regeneration."""

import logging
from typing import Optional


from consts.const import LANGUAGE
from database.agent_db import query_all_agent_info_by_tenant_id
from utils.llm_utils import call_llm_for_system_prompt
from nexent.core.agents.prompt.meta import (
    compose_name_regeneration, load_generation_template,
    render_name_template as _render_prompt_template,
)
from utils.prompt_template_utils import normalize_prompt_generate_template_content

logger = logging.getLogger(__name__)


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
    if user_id is not None:
        from services.prompt_template_service import resolve_prompt_generate_template

        template = resolve_prompt_generate_template(
            tenant_id=tenant_id, user_id=user_id, language=language,
            prompt_template_id=prompt_template_id,
        )
    else:
        template = normalize_prompt_generate_template_content(
            load_generation_template(language)
        )
    values = {value for value in existing_values if value}
    empty_values = "无" if (language or "").lower().startswith(LANGUAGE["ZH"]) else "None"
    prompt = compose_name_regeneration(
        language, template,
        field_key=field_key,
        task_description=task_description or "",
        original_value=original_value,
        existing_values=", ".join(sorted(values)) if values else empty_values,
    )
    last_error = None
    for attempt in range(1, 6):
        try:
            value = call_llm_for_system_prompt(
                model_id=model_id, user_prompt=prompt.user, system_prompt=prompt.system,
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
