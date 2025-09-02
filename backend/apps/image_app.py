import logging
from urllib.parse import unquote

import aiohttp
from fastapi import APIRouter

from consts.const import DATA_PROCESS_SERVICE

# Create router
router = APIRouter()

# Configure logging
logger = logging.getLogger("image_app")


# TODO: To remove this proxy service after frontend uses image filter service as image provider
@router.get("/image")
async def proxy_image(url: str):
    """
    Image proxy service that fetches remote images and returns base64 encoded data

    Parameters:
        url: Remote image URL

    Returns:
        JSON object containing base64 encoded image
    """
    try:
        # URL decode
        decoded_url = unquote(url)

        # Create session to call the data processing service
        async with aiohttp.ClientSession() as session:
            # Call the data processing service to load the image
            data_process_url = f"{DATA_PROCESS_SERVICE}/tasks/load_image?url={decoded_url}"

            async with session.get(data_process_url) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.warning(
                        f"Failed to fetch image from data process service: {error_text}")
                    return {"success": False, "error": "Failed to fetch image or image format not supported"}

                result = await response.json()
                return result

    except Exception as e:
        logger.error(
            f"Error occurred while proxying image: {str(e)}, URL: {url[:50]}...")
        return {"success": False, "error": str(e)}
