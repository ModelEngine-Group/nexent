import logging
import os
from typing import Dict, Any, Optional

import yaml

from consts.const import LANGUAGE

logger = logging.getLogger("prompt_template_utils")


def get_prompt_template(template_type: str, language: str = LANGUAGE["ZH"], **kwargs) -> Dict[str, Any]:
    """
    Get prompt template

    Args:
        template_type: Template type, supports the following values:
            - 'prompt_generate': Prompt generation template
            - 'agent': Agent template including manager and managed agents
            - 'generate_title': Title generation template
            - 'document_summary': Document summary template (Map stage)
            - 'cluster_summary_reduce': Cluster summary reduce template (Reduce stage)
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
        }
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
    existing_skill: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """
    Get skill creation simple prompt template with Jinja2 rendering.

    This template is structured YAML with system_prompt and user_prompt sections.
    Supports Jinja2 template syntax for dynamic content based on existing_skill.

    Args:
        language: Language code ('zh' or 'en')
        existing_skill: Optional dict containing existing skill info for update scenarios.
            Expected keys: name, description, tags, content

    Returns:
        Dict[str, str]: Template with keys 'system_prompt' and 'user_prompt', rendered with variables
    """
    from jinja2 import Template

    template_path_map = {
        LANGUAGE["ZH"]: 'backend/prompts/skill_creation_simple_zh.yaml',
        LANGUAGE["EN"]: 'backend/prompts/skill_creation_simple_en.yaml'
    }

    template_path = template_path_map.get(language, template_path_map[LANGUAGE["ZH"]])

    current_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(current_dir)
    absolute_template_path = os.path.join(backend_dir, template_path.replace('backend/', ''))

    with open(absolute_template_path, 'r', encoding='utf-8') as f:
        template_data = yaml.safe_load(f)

    # Prepare template context with existing_skill info
    context = {
        "existing_skill": existing_skill
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
