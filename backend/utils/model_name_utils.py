import logging
from typing import List

def split_repo_name(full_name: str):
    """
    Split model_name into model_repo and model_name
    """
    parts = full_name.split('/')
    if len(parts) > 1:
        return '/'.join(parts[:-1]), parts[-1]
    return "", full_name


def add_repo_to_name(model_repo: str, model_name: str) -> str:
    """
    Concatenate model_repo and model_name

    Args:
        model_repo: Model repository name
        model_name: Model name

    Returns:
        str: Complete model name after concatenation
    """
    if "/" in model_name:
        logging.warning(f"Unexpected behavior: Model name {model_name} already contains repository information!")
        return model_name
    if model_repo:
        return f"{model_repo}/{model_name}"
    return model_name

def split_display_name(full_name: str):
    """
    Split model_name into a display name.
    Examples:
    - 'model' -> 'model'
    - 'repo/model' -> 'model'
    - 'pro/repo/model' -> 'pro/model'
    """
    parts = full_name.split('/')
    if not full_name:
        return ""
    if len(parts) <= 2:
        return parts[-1]
    else:
        # For names like "Pro/Qwen/Qwen2-7B-Instruct", return "Pro/Qwen2-7B-Instruct"
        return f"{parts[0]}/{parts[-1]}"


def sort_models_by_id(model_list: List[dict]) -> List[dict]:
    """
    Sort model list by the first letter of id
    
    Args:
        model_list: List of models
        
    Returns:
        List[dict]: Sorted model list
    """
    if isinstance(model_list, list):
        model_list.sort(
            key=lambda m: str((m.get("id") if isinstance(m, dict) else m) or "")[:1].lower(), 
            reverse=False
        )
    return model_list
