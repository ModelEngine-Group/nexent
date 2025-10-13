import logging
import os
from typing import Dict, Any

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
            - 'knowledge_summary': Knowledge summary template
            - 'async_knowledge_summary': Async knowledge summary template
            - 'analyze_file': File analysis template
            - 'generate_title': Title generation template
            - 'file_processing_messages': File processing messages template
        language: Language code ('zh' or 'en')
        **kwargs: Additional parameters, for agent type need to pass is_manager parameter

    Returns:
        dict: Loaded prompt template
    """
    logger.info(
        f"Getting prompt template for type: {template_type}, language: {language}, kwargs: {kwargs}")

    # Define template path mapping
    template_paths = {
        'prompt_generate': {
            LANGUAGE["ZH"]: 'backend/prompts/utils/prompt_generate.yaml',
            LANGUAGE["EN"]: 'backend/prompts/utils/prompt_generate_en.yaml'
        },
        'agent': {
            LANGUAGE["ZH"]: {
                'manager': 'backend/prompts/manager_system_prompt_template.yaml',
                'managed': 'backend/prompts/managed_system_prompt_template.yaml'
            },
            LANGUAGE["EN"]: {
                'manager': 'backend/prompts/manager_system_prompt_template_en.yaml',
                'managed': 'backend/prompts/managed_system_prompt_template_en.yaml'
            }
        },
        'knowledge_summary': {
            LANGUAGE["ZH"]: 'backend/prompts/knowledge_summary_agent.yaml',
            LANGUAGE["EN"]: 'backend/prompts/knowledge_summary_agent_en.yaml'
        },
        'async_knowledge_summary': {
            LANGUAGE["ZH"]: 'backend/prompts/async_knowledge_summary.yaml',
            LANGUAGE["EN"]: 'backend/prompts/async_knowledge_summary_en.yaml'
        },
        'analyze_file': {
            LANGUAGE["ZH"]: 'backend/prompts/analyze_file.yaml',
            LANGUAGE["EN"]: 'backend/prompts/analyze_file_en.yaml'
        },
        'generate_title': {
            LANGUAGE["ZH"]: 'backend/prompts/utils/generate_title.yaml',
            LANGUAGE["EN"]: 'backend/prompts/utils/generate_title_en.yaml'
        },
        'file_processing_messages': {
            LANGUAGE["ZH"]: 'backend/prompts/utils/file_processing_messages.yaml',
            LANGUAGE["EN"]: 'backend/prompts/utils/file_processing_messages_en.yaml'
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


def get_knowledge_summary_prompt_template(language: str = 'zh') -> Dict[str, Any]:
    """
    Get knowledge summary prompt template

    Args:
        language: Language code ('zh' or 'en')

    Returns:
        dict: Loaded prompt template configuration
    """
    return get_prompt_template('knowledge_summary', language)


def get_analyze_file_prompt_template(language: str = 'zh') -> Dict[str, Any]:
    """
    Get file analysis prompt template

    Args:
        language: Language code ('zh' or 'en')

    Returns:
        dict: Loaded prompt template configuration
    """
    return get_prompt_template('analyze_file', language)


def get_generate_title_prompt_template(language: str = 'zh') -> Dict[str, Any]:
    """
    Get title generation prompt template

    Args:
        language: Language code ('zh' or 'en')

    Returns:
        dict: Loaded prompt template configuration
    """
    return get_prompt_template('generate_title', language)


def get_file_processing_messages_template(language: str = 'zh') -> Dict[str, Any]:
    """
    Get file processing messages template

    Args:
        language: Language code ('zh' or 'en')

    Returns:
        dict: Loaded file processing messages configuration
    """
    return get_prompt_template('file_processing_messages', language)


def get_async_knowledge_summary_prompt_template(language: str = 'zh') -> Dict[str, Any]:
    """
    Get async knowledge summary prompt template

    Args:
        language: Language code ('zh' or 'en')

    Returns:
        dict: Loaded async knowledge summary prompt template configuration
    """
    return get_prompt_template('async_knowledge_summary', language)
