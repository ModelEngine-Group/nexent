import base64
import logging
from http import HTTPStatus
from urllib.parse import urlparse

import aiohttp

from consts.const import DATA_PROCESS_SERVICE
from consts.const import MODEL_CONFIG_MAPPING
from utils.config_utils import tenant_config_manager, get_model_name_from_config

from nexent import MessageObserver
from nexent.core.models import OpenAIVLModel

logger = logging.getLogger("image_service")


def _is_loopback_image_url(decoded_url: str) -> bool:
    try:
        parsed = urlparse(decoded_url)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    return parsed.hostname in {"127.0.0.1", "localhost"}


async def _fetch_image_directly(decoded_url: str):
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(decoded_url) as response:
            if response.status != HTTPStatus.OK:
                error_text = await response.text()
                logger.error(
                    "Failed to fetch loopback image directly: %s", error_text
                )
                return {"success": False, "error": "Failed to fetch image"}

            content = await response.read()
            content_type = response.headers.get("Content-Type", "image/jpeg")
            return {
                "success": True,
                "base64": base64.b64encode(content).decode("utf-8"),
                "content_type": content_type,
            }


async def proxy_image_impl(decoded_url: str):
    if _is_loopback_image_url(decoded_url):
        return await _fetch_image_directly(decoded_url)

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


def get_vlm_model(tenant_id: str):
    """Return the configured image understanding model for AnalyzeImageTool.

    The first multimodal model slot is still stored under MODEL_CONFIG_MAPPING["vlm"]
    for compatibility, but it is the user-facing image understanding configuration.
    """
    vlm_model_config = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["vlm"], tenant_id=tenant_id)
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
    )


def get_image_understanding_model(tenant_id: str):
    return get_vlm_model(tenant_id=tenant_id)


def get_video_understanding_model(tenant_id: str):
    """Return the configured video understanding model for multimodal tools."""
    vlm_model_config = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["vlm3"], tenant_id=tenant_id)
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
    )
