import logging
from http import HTTPStatus

import aiohttp

from consts.const import DATA_PROCESS_SERVICE
from consts.const import MODEL_CONFIG_MAPPING
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

def get_vlm_model(tenant_id: str):
    # Get the tenant config
    vlm_model_config = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["vlm"], tenant_id=tenant_id)
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
