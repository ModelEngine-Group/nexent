# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared tenant-scoped Agent naming rules and LLM regeneration."""

import logging

from nexent.core.agent_names import AGENT_NAME_MAX_LENGTH, validate_agent_name

from consts.const import LANGUAGE
from database.agent_db import query_all_agent_info_by_tenant_id
from management.services.agent.prompt import (
    load_default_generation_prompt,
)
from management.services.model.invocation import call_llm_for_system_prompt
from nexent.core.agents.prompt.meta import (
    compose_name_regeneration,
)

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
    agents = (
        agents_cache
        if agents_cache is not None
        else query_all_agent_info_by_tenant_id(tenant_id)
    )
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
        suffix = f"_{counter}"
        if field_key == "name":
            try:
                validate_agent_name(base_value)
                base = base_value
            except ValueError:
                base = "agent"
            candidate = f"{base[:AGENT_NAME_MAX_LENGTH - len(suffix)]}{suffix}"
            validate_agent_name(candidate)
        else:
            candidate = f"{base_value}{suffix}"
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
) -> str:
    """Regenerate one naming field with five attempts and suffix fallback."""
    template = load_default_generation_prompt(language)
    values = {value for value in existing_values if value}
    empty_values = (
        "无" if (language or "").lower().startswith(LANGUAGE["ZH"]) else "None"
    )
    prompt = compose_name_regeneration(
        language,
        template,
        field_key=field_key,
        task_description=task_description or "",
        original_value=original_value,
        existing_values=", ".join(sorted(values)) if values else empty_values,
    )
    last_error = None
    for attempt in range(1, 6):
        try:
            value = call_llm_for_system_prompt(
                model_id=model_id,
                user_prompt=prompt.user,
                system_prompt=prompt.system,
                callback=None,
                tenant_id=tenant_id,
            )
            candidate = (value or "").strip().splitlines()[0].strip()
            if field_key == "name":
                validate_agent_name(candidate)
            if candidate in values:
                raise ValueError(f"Generated duplicate value '{candidate}'")
            return candidate
        except Exception as exc:
            last_error = exc
            logger.warning("Attempt %s/5 to regenerate value failed: %s", attempt, exc)
    logger.error(
        "Failed to regenerate agent value with LLM after maximum retries",
        exc_info=last_error,
    )
    return generate_unique_agent_value(
        field_key, original_value, tenant_id, agents_cache, exclude_agent_id
    )
