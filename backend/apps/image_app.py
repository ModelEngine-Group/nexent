import logging
from urllib.parse import unquote

from fastapi import APIRouter

from services.image_service import proxy_image_impl

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
        return await proxy_image_impl(decoded_url)
    except Exception as e:
        logger.error(
            f"Error occurred while proxying image: {str(e)}, URL: {url[:50]}...")
        return {"success": False, "error": str(e)}