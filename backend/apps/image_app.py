import logging
import base64
from urllib.parse import unquote
from io import BytesIO

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from services.image_service import proxy_image_impl

# Create router
router = APIRouter()

# Configure logging
logger = logging.getLogger("image_app")


# TODO: To remove this proxy service after frontend uses image filter service as image provider
@router.get("/image")
async def proxy_image(url: str, format: str = "json"):
    """
    Image proxy service that fetches remote images
    
    Parameters:
        url: Remote image URL
        format: Response format - "json" (default, returns base64) or "stream" (returns image stream)

    Returns:
        JSON object containing base64 encoded image (format=json) or image stream (format=stream)
    """
    try:
        # URL decode
        decoded_url = unquote(url)
        
        if format == "stream":
            # Return image as stream for direct use in <img> tags
            result = await proxy_image_impl(decoded_url)
            if not result.get("success"):
                from fastapi import HTTPException
                from http import HTTPStatus
                raise HTTPException(
                    status_code=HTTPStatus.BAD_GATEWAY,
                    detail=result.get("error", "Failed to fetch image")
                )
            
            # Decode base64 to bytes
            base64_data = result.get("base64", "")
            content_type = result.get("content_type", "image/jpeg")
            image_bytes = base64.b64decode(base64_data)
            
            # Return as streaming response
            return StreamingResponse(
                BytesIO(image_bytes),
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=3600"
                }
            )
        else:
            # Return JSON with base64 (default behavior for backward compatibility)
            return await proxy_image_impl(decoded_url)
    except Exception as e:
        logger.error(
            f"Error occurred while proxying image: {str(e)}, URL: {url[:50]}...")
        if format == "stream":
            from fastapi import HTTPException
            from http import HTTPStatus
            raise HTTPException(
                status_code=HTTPStatus.BAD_GATEWAY,
                detail=str(e)
            )
        return {"success": False, "error": str(e)}