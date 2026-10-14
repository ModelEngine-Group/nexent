import logging
from typing import Any, Dict, List, Optional

from consts.const import LANGUAGE
from consts.prompt_template import (
    PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP,
    PROMPT_GENERATE_TEMPLATE_FIELDS,
)
from nexent.core.agents.prompt.meta import compose_nl2skill

logger = logging.getLogger("prompt_template_utils")

PROMPT_GENERATE_TEMPLATE_KEY_MAP = PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP
PROMPT_GENERATE_TEMPLATE_KEYS = PROMPT_GENERATE_TEMPLATE_FIELDS


def get_prompt_generate_template_keys() -> list[str]:
    """Return the supported prompt generation template keys."""
    return list(PROMPT_GENERATE_TEMPLATE_FIELDS)


def normalize_prompt_generate_template_content(
    template_content: Optional[Dict[str, Any]]
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
    *template_contents: Optional[Dict[str, Any]]
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


def get_nl2skill_prompt_template(
    language: str = LANGUAGE["ZH"],
    existing_skill: Optional[Dict[str, Any]] = None,
    user_request: str = "",
    target_files: Optional[List[str]] = None,
) -> Dict[str, str]:
    """
    Get skill creation prompt template with Jinja2 rendering.

    This template is structured YAML with system_prompt and user_prompt sections.
    Supports Jinja2 template syntax for dynamic content based on existing_skill.

    Args:
        language: Language code ('zh' or 'en')
        existing_skill: Optional dict containing existing skill info for update scenarios.
            Expected keys: name, description, tags, content
        user_request: Current conversation turn request
        target_files: Existing skill files explicitly selected for this turn

    Returns:
        Dict[str, str]: Template with keys 'system_prompt' and 'user_prompt', rendered with variables
    """
    template_language = language if language in {LANGUAGE["ZH"], LANGUAGE["EN"]} else LANGUAGE["ZH"]
    return compose_nl2skill(
        template_language,
        existing_skill=existing_skill,
        user_request=user_request,
        target_files=target_files or [],
    )
