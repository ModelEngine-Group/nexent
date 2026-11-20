# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from typing import Any, Dict, List


def split_repo_name(full_name: str):
    """
    Split model_name into model_repo and model_name
    """
    parts = full_name.split("/")
    if len(parts) > 1:
        return "/".join(parts[:-1]), parts[-1]
    return "", full_name


from nexent.core.model_service.compatibility.model_names import add_repo_to_name as add_repo_to_name


def split_display_name(full_name: str):
    """
    Split model_name into a display name.
    Examples:
    - 'model' -> 'model'
    - 'repo/model' -> 'model'
    - 'pro/repo/model' -> 'pro/model'
    """
    parts = full_name.split("/")
    if not full_name:
        return ""
    if len(parts) <= 2:
        return parts[-1]
    else:
        # For names like "Pro/Qwen/Qwen2-7B-Instruct", return "Pro/Qwen2-7B-Instruct"
        return f"{parts[0]}/{parts[-1]}"


def sort_models_by_id(model_list: List[dict]) -> List[dict]:
    """
    Sort model list by the full id, case-insensitively

    Args:
        model_list: List of models

    Returns:
        List[dict]: Sorted model list
    """
    if isinstance(model_list, list):
        model_list.sort(
            key=lambda m: str((m.get("id") if isinstance(m, dict) else m) or "").lower(),
            reverse=False,
        )
    return model_list


def get_model_name_from_config(model_config: Dict[str, Any]) -> str:
    """Get model name from model id"""
    if model_config is None:
        return ""
    # Quick-config entries may omit model_repo; treat it as an empty repo.
    model_repo = model_config.get("model_repo") or ""
    model_name = model_config.get("model_name") or model_config.get("modelName") or ""
    if not model_repo:
        return model_name
    return f"{model_repo}/{model_name}"
