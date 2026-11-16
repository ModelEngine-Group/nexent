# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import logging
import base64
from urllib.parse import unquote
from io import BytesIO

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from http import HTTPStatus

from management.services.file.image_proxy import proxy_image_impl
from management.services.permission.identity.session import get_current_user_id

# Create router
router = APIRouter()

# Configure logging
logger = logging.getLogger("image_app")


@router.get("/image")
async def proxy_image(url: str, format: str = "json", authorization: str | None = Header(None)):
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
        identity = {}
        if decoded_url.lower().startswith("s3://"):
            user_id, tenant_id = get_current_user_id(authorization)
            identity = {"user_id": user_id, "tenant_id": tenant_id}

        if format == "stream":
            # Return image as stream for direct use in <img> tags
            result = await proxy_image_impl(decoded_url, **identity)
            if not result.get("success"):
                raise HTTPException(
                    status_code=HTTPStatus.BAD_GATEWAY,
                    detail="Failed to fetch image"
                )

            # Decode base64 to bytes
            base64_data = result.get("base64", "")
            content_type = result.get("content_type", "image/jpeg")
            image_bytes = base64.b64decode(base64_data)

            # Return as streaming response
            return StreamingResponse(
                BytesIO(image_bytes), media_type=content_type, headers={"Cache-Control": "public, max-age=3600"}
            )
        else:
            # Return JSON with base64 (default behavior for backward compatibility)
            result = await proxy_image_impl(decoded_url, **identity)
            if not result.get("success"):
                return {"success": False, "error": "Failed to fetch image"}
            return result
    except TimeoutError:
        logger.warning("image_proxy_timeout phase=content threshold_seconds=5")
        if format == "stream":
            raise HTTPException(status_code=HTTPStatus.BAD_GATEWAY, detail="Failed to fetch image") from None
        return {"success": False, "error": "Failed to fetch image"}
    except Exception:
        logger.exception("Error occurred while proxying image")
        if format == "stream":
            raise HTTPException(
                status_code=HTTPStatus.BAD_GATEWAY,
                detail="Failed to fetch image"
            ) from None
        return {"success": False, "error": "Failed to fetch image"}
