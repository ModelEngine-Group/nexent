import logging
import os
from typing import Any, Dict, List, Optional

import yaml

from consts.const import LANGUAGE
from consts.prompt_template import (
    PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP,
    PROMPT_GENERATE_TEMPLATE_FIELDS,
)

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


def get_prompt_template(template_type: str, language: str = LANGUAGE["ZH"], **kwargs) -> Dict[str, Any]:
    """
    Get prompt template

    Args:
        template_type: Template type, supports the following values:
            - 'prompt_generate': Prompt generation template
            - 'prompt_optimize': Prompt section optimization template
            - 'agent': Agent template including manager and managed agents
            - 'generate_title': Title generation template
            - 'document_summary': Document summary template (Map stage)
            - 'cluster_summary_reduce': Cluster summary reduce template (Reduce stage)
            - 'nl2agent': NL2Agent runtime system prompt
        language: Language code ('zh' or 'en')
        **kwargs: Additional parameters, for agent type need to pass is_manager parameter

    Returns:
        dict: Loaded prompt template
    """

    # Define template path mapping
    template_paths = {
        'prompt_generate': {
            LANGUAGE["ZH"]: 'backend/prompts/utils/prompt_generate_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/utils/prompt_generate_en.yaml'
        },
        'prompt_optimize': {
            LANGUAGE["ZH"]: 'backend/prompts/utils/prompt_optimize_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/utils/prompt_optimize_en.yaml'
        },
        'agent': {
            LANGUAGE["ZH"]: {
                'manager': 'backend/prompts/manager_system_prompt_template_zh.yaml',
                'managed': 'backend/prompts/managed_system_prompt_template_zh.yaml'
            },
            LANGUAGE["EN"]: {
                'manager': 'backend/prompts/manager_system_prompt_template_en.yaml',
                'managed': 'backend/prompts/managed_system_prompt_template_en.yaml'
            }
        },
        'generate_title': {
            LANGUAGE["ZH"]: 'backend/prompts/utils/generate_title_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/utils/generate_title_en.yaml'
        },
        'greeting_generate': {
            LANGUAGE["ZH"]: 'backend/prompts/utils/greeting_generate_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/utils/greeting_generate_en.yaml'
        },
        'document_summary': {
            LANGUAGE["ZH"]: 'backend/prompts/document_summary_agent_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/document_summary_agent_en.yaml'
        },
        'cluster_summary_reduce': {
            LANGUAGE["ZH"]: 'backend/prompts/cluster_summary_reduce_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/cluster_summary_reduce_en.yaml'
        },
        'skill_creation_simple': {
            LANGUAGE["ZH"]: 'backend/prompts/skill_creation_simple_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/skill_creation_simple_en.yaml'
        },
        'skill_creation_complicated': {
            LANGUAGE["ZH"]: 'backend/prompts/skill_creation_complicate_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/skill_creation_complicate_en.yaml'
        },
        'guardrail_regex': {
            LANGUAGE["ZH"]: 'backend/prompts/utils/guardrail_regex_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/utils/guardrail_regex_en.yaml'
        },
        'agent_automation': {
            LANGUAGE["ZH"]: 'backend/prompts/agent_automation_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/agent_automation_en.yaml'
        },
        'nl2agent': {
            LANGUAGE["ZH"]: 'backend/prompts/nl2agent_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/nl2agent_en.yaml'
        },
        'evaluation_generate_evaluator': {
            LANGUAGE["ZH"]: 'backend/prompts/evaluation/generate_evaluator_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/evaluation/generate_evaluator_en.yaml'
        },
        'evaluation_generate_queries': {
            LANGUAGE["ZH"]: 'backend/prompts/evaluation/generate_cases_system_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/evaluation/generate_cases_system_en.yaml'
        },
        'evaluation_error_explain': {
            LANGUAGE["ZH"]: 'backend/prompts/evaluation/error_explain_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/evaluation/error_explain_en.yaml'
        },
        'evaluation_plan_kb_queries': {
            LANGUAGE["ZH"]: 'backend/prompts/evaluation/plan_kb_queries_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/evaluation/plan_kb_queries_en.yaml'
        },
        'evaluation_generate_cases_system': {
            LANGUAGE["ZH"]: 'backend/prompts/evaluation/generate_cases_system_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/evaluation/generate_cases_system_en.yaml'
        },
        'evaluation_judge_system': {
            LANGUAGE["ZH"]: 'backend/prompts/evaluation/judge_system_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/evaluation/judge_system_en.yaml'
        },
        'evaluation_analyze_report': {
            LANGUAGE["ZH"]: 'backend/prompts/evaluation/analyze_report_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/evaluation/analyze_report_en.yaml'
        },
    }

    if template_type not in template_paths:
        raise ValueError(f"Unsupported template type: {template_type}")

    # Get template path
    if template_type == 'agent':
        is_manager = kwargs.get('is_manager', False)
        agent_type = 'manager' if is_manager else 'managed'
        template_path = template_paths[template_type][language][agent_type]
    else:
        template_path = template_paths[template_type][language]

    # Get the directory of this file and construct absolute path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up one level from utils to backend, then use the template path
    backend_dir = os.path.dirname(current_dir)
    absolute_template_path = os.path.join(backend_dir, template_path.replace('backend/', ''))

    # Read and return template content
    with open(absolute_template_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# For backward compatibility, keep original function names as wrapper functions
def get_prompt_generate_prompt_template(language: str = LANGUAGE["ZH"]) -> Dict[str, Any]:
    """
    Get prompt generation prompt template

    Args:
        language: Language code ('zh' or 'en')

    Returns:
        dict: Loaded prompt template configuration
    """
    return get_prompt_template('prompt_generate', language)


def get_prompt_optimize_prompt_template(language: str = LANGUAGE["ZH"]) -> Dict[str, Any]:
    """
    Get prompt optimization template.

    Args:
        language: Language code ('zh' or 'en')

    Returns:
        dict: Loaded prompt optimization template configuration
    """
    return get_prompt_template('prompt_optimize', language)


def get_guardrail_regex_prompt_template(language: str = LANGUAGE["ZH"]) -> Dict[str, Any]:
    """Load the guardrail regex generation prompt template.

    Args:
        language: Language code ('zh' or 'en') selecting the template variant.

    Returns:
        The loaded template configuration dict, carrying the
        ``GUARDRAIL_SYSTEM_PROMPT`` and ``GUARDRAIL_USER_PROMPT`` keys.
    """
    return get_prompt_template('guardrail_regex', language)


def get_agent_prompt_template(is_manager: bool, language: str = LANGUAGE["ZH"]) -> Dict[str, Any]:
    """
    Get agent prompt template

    Args:
        is_manager: Whether it is manager mode
        language: Language code ('zh' or 'en')

    Returns:
        dict: Loaded prompt template configuration
    """
    return get_prompt_template('agent', language, is_manager=is_manager)


def get_generate_title_prompt_template(language: str = 'zh') -> Dict[str, Any]:
    """
    Get title generation prompt template

    Args:
        language: Language code ('zh' or 'en')

    Returns:
        dict: Loaded prompt template configuration
    """
    return get_prompt_template('generate_title', language)


def get_document_summary_prompt_template(language: str = LANGUAGE["ZH"]) -> Dict[str, Any]:
    """
    Get document summary prompt template (Map stage)

    Args:
        language: Language code ('zh' or 'en')

    Returns:
        dict: Loaded document summary prompt template configuration
    """
    return get_prompt_template('document_summary', language)


def get_cluster_summary_reduce_prompt_template(language: str = LANGUAGE["ZH"]) -> Dict[str, Any]:
    """
    Get cluster summary reduce prompt template (Reduce stage)

    Args:
        language: Language code ('zh' or 'en')

    Returns:
        dict: Loaded cluster summary reduce prompt template configuration
    """
    return get_prompt_template('cluster_summary_reduce', language)


def get_skill_creation_simple_prompt_template(
    language: str = LANGUAGE["ZH"],
    existing_skill: Optional[Dict[str, Any]] = None,
    complexity: str = "simple",
    user_request: str = "",
    target_files: Optional[List[str]] = None,
) -> Dict[str, str]:
    """
    Get skill creation prompt template with Jinja2 rendering.

    This template is structured YAML with system_prompt and user_prompt sections.
    Supports Jinja2 template syntax for dynamic content based on existing_skill.
    Supports both simple and complicated skill creation templates.

    Args:
        language: Language code ('zh' or 'en')
        existing_skill: Optional dict containing existing skill info for update scenarios.
            Expected keys: name, description, tags, content
        complexity: Complexity level ('simple' or 'complicated')
        user_request: Current conversation turn request
        target_files: Existing skill files explicitly selected for this turn

    Returns:
        Dict[str, str]: Template with keys 'system_prompt' and 'user_prompt', rendered with variables
    """
    from jinja2 import Template

    # Select template based on complexity
    template_path_map = {
        "simple": {
            LANGUAGE["ZH"]: 'backend/prompts/skill_creation_simple_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/skill_creation_simple_en.yaml'
        },
        "complicated": {
            LANGUAGE["ZH"]: 'backend/prompts/skill_creation_complicate_zh.yaml',
            LANGUAGE["EN"]: 'backend/prompts/skill_creation_complicate_en.yaml'
        }
    }

    # Default to simple if complexity is not recognized
    template_type = template_path_map.get(complexity, template_path_map["simple"])
    template_path = template_type.get(language, template_type[LANGUAGE["ZH"]])

    current_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(current_dir)
    absolute_template_path = os.path.join(backend_dir, template_path.replace('backend/', ''))

    with open(absolute_template_path, 'r', encoding='utf-8') as f:
        template_data = yaml.safe_load(f)

    # A draft snapshot is supplied for every interactive turn, including the empty initial draft.
    existing_skill_content = ""
    if isinstance(existing_skill, dict):
        existing_skill_content = str(existing_skill.get("content") or "").strip()

    # Prepare template context with existing_skill info.
    context = {
        "existing_skill": existing_skill,
        "has_existing_skill_content": bool(existing_skill_content),
        "user_request": user_request,
        "target_files": target_files or [],
    }

    # Render templates with Jinja2
    system_prompt_raw = template_data.get("system_prompt", "")
    user_prompt_raw = template_data.get("user_prompt", "")

    try:
        system_prompt = Template(system_prompt_raw).render(**context)
    except Exception as e:
        logger.warning(f"Failed to render system_prompt template: {e}, using raw content")
        system_prompt = system_prompt_raw

    try:
        user_prompt = Template(user_prompt_raw).render(**context)
    except Exception as e:
        logger.warning(f"Failed to render user_prompt template: {e}, using raw content")
        user_prompt = user_prompt_raw

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt
    }
