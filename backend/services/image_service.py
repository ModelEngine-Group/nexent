import logging
from http import HTTPStatus
from typing import Optional

import aiohttp

from consts.const import DATA_PROCESS_SERVICE
from consts.const import MODEL_CONFIG_MAPPING
from database.model_management_db import get_model_by_model_id
from utils.config_utils import tenant_config_manager, get_model_name_from_config

from nexent import MessageObserver
from nexent.core.models import OpenAIVLModel

logger = logging.getLogger("image_service")


async def proxy_image_impl(decoded_url: str):
    # Create session to call the data processing service
    async with aiohttp.ClientSession() as session:
        # Call the data processing service to load the image
        data_process_url = f"{DATA_PROCESS_SERVICE}/tasks/load_image?url={decoded_url}"

        async with session.get(data_process_url) as response:
            if response.status != HTTPStatus.OK:
                error_text = await response.text()
                logger.error(
                    f"Failed to fetch image from data process service: {error_text}")
                return {"success": False, "error": "Failed to fetch image or image format not supported"}

            result = await response.json()
            return result


def _get_model_config_by_id(tenant_id, model_id, expected_model_type):
    if not model_id:
        return None

    model_config = get_model_by_model_id(int(model_id), tenant_id)
    if not model_config:
        raise ValueError(f"Model not found: {model_id}")
    if model_config.get("model_type") != expected_model_type:
        raise ValueError(f"Selected model {model_id} is not a {expected_model_type} model")
    return model_config


def _build_vlm_model(vlm_model_config):
    if not vlm_model_config:
        return None
    return OpenAIVLModel(
        observer=MessageObserver(),
        model_id=get_model_name_from_config(
            vlm_model_config) if vlm_model_config else "",
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
            key=MODEL_CONFIG_MAPPING["vlm"], tenant_id=tenant_id)
    return _build_vlm_model(vlm_model_config)


def get_image_understanding_model(tenant_id: str):
    return get_vlm_model(tenant_id=tenant_id)


def get_video_understanding_model(tenant_id: str, model_id: Optional[int] = None):
    """Return the configured video understanding model for multimodal tools."""
    if model_id:
        vlm_model_config = _get_model_config_by_id(tenant_id, model_id, "vlm3")
    else:
        vlm_model_config = tenant_config_manager.get_model_config(
            key=MODEL_CONFIG_MAPPING["vlm3"], tenant_id=tenant_id)
    return _build_vlm_model(vlm_model_config)
