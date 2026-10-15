"""Agent template selection, normalization and visible-tool prompt policy."""

import logging
from collections.abc import Iterable, Mapping
from typing import Any, Dict, Optional

from consts.prompt_template import (
    PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP,
    PROMPT_GENERATE_TEMPLATE_FIELDS,
)
from nexent.core.agents.prompt import AgentPromptBundle


def load_agent_prompt_bundle(
    *,
    is_manager: bool,
    language: str,
    template_override: Mapping | None = None,
) -> AgentPromptBundle:
    """Select a YAML template and delegate its contract validation to the SDK."""
    role = "manager" if is_manager else "managed"
    if language not in {"zh", "en"}:
        raise ValueError("unsupported Agent prompt language")
    return AgentPromptBundle.from_resource(
        role=role,
        language=language,
        template_override=template_override,
    )


logger = logging.getLogger("prompt_template_utils")


PROMPT_GENERATE_TEMPLATE_KEY_MAP = PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP


PROMPT_GENERATE_TEMPLATE_KEYS = PROMPT_GENERATE_TEMPLATE_FIELDS


def get_prompt_generate_template_keys() -> list[str]:
    """Return the supported prompt generation template keys."""
    return list(PROMPT_GENERATE_TEMPLATE_FIELDS)


def normalize_prompt_generate_template_content(
    template_content: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """Normalize prompt generation template content and keep non-empty fields only."""
    normalized: Dict[str, str] = {}
    if not isinstance(template_content, dict):
        return normalized

    for key in PROMPT_GENERATE_TEMPLATE_FIELDS:
        legacy_key = PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP[key]
        value = template_content.get(key)
        if value is None:
            value = template_content.get(legacy_key)
        if isinstance(value, str) and value.strip():
            normalized[key] = value

    return normalized


def merge_prompt_generate_templates(
    *template_contents: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """Merge multiple prompt generation templates with first-non-empty priority."""
    merged: Dict[str, str] = {}

    for template_content in template_contents:
        normalized = normalize_prompt_generate_template_content(template_content)
        for key in PROMPT_GENERATE_TEMPLATE_FIELDS:
            value = normalized.get(key)
            if value and key not in merged:
                merged[key] = value

    return merged


def should_enable_memory_tool_policy(tool_names: Iterable[str]) -> bool:
    """Enable memory guidance only for a final visible store tool."""
    return "store_memory" in set(tool_names)


AUTOMATION_TOOL_NAME = "create_scheduled_task_proposal"


def should_enable_automation_tool_policy(tool_names: Iterable[str]) -> bool:
    """Enable proposal guidance only for a final visible proposal tool."""
    return AUTOMATION_TOOL_NAME in set(tool_names)
