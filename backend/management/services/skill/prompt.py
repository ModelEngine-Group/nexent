"""Skill creation prompt adapter."""

from typing import Any, Dict, List, Optional

from consts.const import LANGUAGE
from nexent.core.agents.prompt.meta import compose_nl2skill


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
    template_language = (
        language if language in {LANGUAGE["ZH"], LANGUAGE["EN"]} else LANGUAGE["ZH"]
    )
    return compose_nl2skill(
        template_language,
        existing_skill=existing_skill,
        user_request=user_request,
        target_files=target_files or [],
    )
