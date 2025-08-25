import yaml
from typing import Dict, Any
import logging
logger = logging.getLogger("prompt_template_utils")


def get_prompt_template(template_type: str, language: str = 'zh', **kwargs) -> Dict[str, Any]:
    """
    Get prompt template
    
    Args:
        template_type: Template type, supports the following values:
            - 'prompt_generate': Prompt generation template
            - 'agent': Agent template including manager and managed agents
            - 'knowledge_summary': Knowledge summary template
            - 'analyze_file': File analysis template
            - 'prompt_fine_tune': Prompt fine-tuning template
            - 'generate_title': Title generation template
        language: Language code ('zh' or 'en')
        **kwargs: Additional parameters, for agent type need to pass is_manager parameter
        
    Returns:
        dict: Loaded prompt template
    """
    logger.info(f"Getting prompt template for type: {template_type}, language: {language}，kwargs: {kwargs}")
    
    # Define template path mapping
    template_paths = {
        'prompt_generate': {
            'zh': 'backend/prompts/utils/prompt_generate.yaml',
            'en': 'backend/prompts/utils/prompt_generate_en.yaml'
        },
        'agent': {
            'zh': {
                'manager': 'backend/prompts/manager_system_prompt_template.yaml',
                'managed': 'backend/prompts/managed_system_prompt_template.yaml'
            },
            'en': {
                'manager': 'backend/prompts/manager_system_prompt_template_en.yaml',
                'managed': 'backend/prompts/managed_system_prompt_template_en.yaml'
            }
        },
        'knowledge_summary': {
            'zh': 'backend/prompts/knowledge_summary_agent.yaml',
            'en': 'backend/prompts/knowledge_summary_agent_en.yaml'
        },
        'analyze_file': {
            'zh': 'backend/prompts/analyze_file.yaml',
            'en': 'backend/prompts/analyze_file_en.yaml'
        },
        'prompt_fine_tune': {
            'zh': 'backend/prompts/utils/prompt_fine_tune.yaml',
            'en': 'backend/prompts/utils/prompt_fine_tune_en.yaml'
        },
        'generate_title': {
            'zh': 'backend/prompts/utils/generate_title.yaml',
            'en': 'backend/prompts/utils/generate_title_en.yaml'
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
    
    # Read and return template content
    with open(template_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# For backward compatibility, keep original function names as wrapper functions
def get_prompt_generate_prompt_template(language: str = 'zh') -> Dict[str, Any]:
    """
    Get prompt generation prompt template
    
    Args:
        language: Language code ('zh' or 'en')
        
    Returns:
        dict: Loaded prompt template configuration
    """
    return get_prompt_template('prompt_generate', language)


def get_agent_prompt_template(is_manager: bool, language: str = 'zh') -> Dict[str, Any]:
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


def get_prompt_fine_tune_prompt_template(language: str = 'zh') -> Dict[str, Any]:
    """
    Get prompt fine-tuning template
    
    Args:
        language: Language code ('zh' or 'en')
        
    Returns:
        dict: Loaded prompt template configuration
    """
    return get_prompt_template('prompt_fine_tune', language)


def get_generate_title_prompt_template(language: str = 'zh') -> Dict[str, Any]:
    """
    Get title generation prompt template
    
    Args:
        language: Language code ('zh' or 'en')
        
    Returns:
        dict: Loaded prompt template configuration
    """
    return get_prompt_template('generate_title', language)
