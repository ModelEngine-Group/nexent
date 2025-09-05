import logging
from http import HTTPStatus

import aiohttp

from consts.const import DATA_PROCESS_SERVICE

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
