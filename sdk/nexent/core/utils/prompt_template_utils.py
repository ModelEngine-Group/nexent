import logging
import os
from typing import Dict, Any

import yaml

LANGUAGE = {
    "ZH": "zh",
    "EN": "en"
}

logger = logging.getLogger("prompt_template_utils")

# Define template path mapping
template_paths = {
    'analyze_image': {
        LANGUAGE["ZH"]: 'core/prompts/analyze_image_zh.yaml',
        LANGUAGE["EN"]: 'core/prompts/analyze_image_en.yaml'
    },
    'analyze_file': {
        LANGUAGE["ZH"]: 'core/prompts/analyze_file_zh.yaml',
        LANGUAGE["EN"]: 'core/prompts/analyze_file_en.yaml'
    }
}

def get_prompt_template(template_type: str, language: str = LANGUAGE["ZH"], **kwargs) -> Dict[str, Any]:
    """
    Get prompt template

    Args:
        template_type: Template type, supports the following values:
            - 'analyze_image': Analyze image template
            - 'analyze_file': Analyze file template (for text files)
        language: Language code ('zh' or 'en')
        **kwargs: Additional parameters, for agent type need to pass is_manager parameter

    Returns:
        dict: Loaded prompt template
    """
    logger.info(
        f"Getting prompt template for type: {template_type}, language: {language}, kwargs: {kwargs}")

    if template_type not in template_paths:
        raise ValueError(f"Unsupported template type: {template_type}")

    # Get template path
    template_path = template_paths[template_type][language]

    # Get the directory of this file and construct absolute path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up one level from utils to core, then use the template path
    core_dir = os.path.dirname(current_dir)
    absolute_template_path = os.path.join(core_dir, template_path.replace('core/', ''))

    # Read and return template content
    with open(absolute_template_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)