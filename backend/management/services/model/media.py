# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


import logging
from typing import Optional

from contracts.constants.model import MODEL_CONFIG_MAPPING
from management.db.model.repository import get_model_by_model_id
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.model.names import get_model_name_from_config
from nexent import MessageObserver
from nexent.core.models import OpenAILongContextModel, OpenAIVLModel

logger = logging.getLogger("management.services.model.resolver")


def _get_model_config_by_id(tenant_id, model_id, expected_model_type):
    if not model_id:
        return None

    model_config = get_model_by_model_id(int(model_id), tenant_id)
    if not model_config:
        raise ValueError(f"Model not found: {model_id}")
    if model_config.get("model_type") != expected_model_type:
        raise ValueError(
            f"Selected model {model_id} is not a {expected_model_type} model"
        )
    return model_config


def _build_vlm_model(vlm_model_config):
    if not vlm_model_config:
        return None
    return OpenAIVLModel(
        observer=MessageObserver(),
        model_id=get_model_name_from_config(vlm_model_config)
        if vlm_model_config
        else "",
        api_base=vlm_model_config.get("base_url", ""),
        api_key=vlm_model_config.get("api_key", ""),
        temperature=0.7,
        top_p=0.7,
        frequency_penalty=0.5,
        max_tokens=512,
        ssl_verify=vlm_model_config.get("ssl_verify", True),
        model_factory=vlm_model_config.get("model_factory"),
        display_name=vlm_model_config.get("display_name"),
    )


def get_vlm_model(tenant_id: str, model_id: Optional[int] = None):
    """Return the configured image understanding model for AnalyzeImageTool.

    The first multimodal model slot is still stored under MODEL_CONFIG_MAPPING["vlm"]
    for compatibility, but it is the user-facing image understanding configuration.
    """
    if model_id:
        vlm_model_config = _get_model_config_by_id(tenant_id, model_id, "vlm")
    else:
        vlm_model_config = tenant_config_manager.get_model_config(
            key=MODEL_CONFIG_MAPPING["vlm"], tenant_id=tenant_id
        )
    return _build_vlm_model(vlm_model_config)


def get_image_understanding_model(tenant_id: str):
    return get_vlm_model(tenant_id=tenant_id)


def get_video_understanding_model(tenant_id: str, model_id: Optional[int] = None):
    """Return the configured video understanding model for multimodal tools."""
    if model_id:
        vlm_model_config = _get_model_config_by_id(tenant_id, model_id, "vlm3")
    else:
        vlm_model_config = tenant_config_manager.get_model_config(
            key=MODEL_CONFIG_MAPPING["vlm3"], tenant_id=tenant_id
        )
    return _build_vlm_model(vlm_model_config)


def get_llm_model(tenant_id: str, model_id: Optional[int] = None):
    if model_id:
        main_model_config = get_model_by_model_id(int(model_id), tenant_id)
        if not main_model_config:
            raise ValueError(f"Model not found: {model_id}")
        if main_model_config.get("model_type") != "llm":
            raise ValueError(f"Selected model {model_id} is not an LLM model")
    else:
        # Get the tenant config
        main_model_config = tenant_config_manager.get_model_config(
            key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id
        )
    timeout_seconds = (
        main_model_config.get("timeout_seconds") if main_model_config else None
    )

    resolved_model_name = get_model_name_from_config(main_model_config)

    logger.info(
        "Using LLM model for analyze_text_file: model_id=%s, display_name=%s, model_name=%s",
        model_id,
        main_model_config.get("display_name") if main_model_config else None,
        resolved_model_name,
    )

    long_text_to_text_model = OpenAILongContextModel(
        observer=MessageObserver(),
        model_id=resolved_model_name,
        api_base=main_model_config.get("base_url"),
        api_key=main_model_config.get("api_key"),
        max_context_tokens=main_model_config.get("max_tokens"),
        ssl_verify=main_model_config.get("ssl_verify", True),
        timeout_seconds=timeout_seconds,
        model_factory=main_model_config.get("model_factory"),
        display_name=main_model_config.get("display_name"),
    )
    return long_text_to_text_model
