# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""External web-image reads; object storage is deliberately a different capability."""

from urllib.parse import urlsplit

from nexent.multi_modal.image_codec import decode_image_bytes
from PIL import Image, UnidentifiedImageError


async def load_web_image(session, url: str) -> Image.Image | None:
    if urlsplit(url).scheme.lower() not in {"http", "https"} or url.lower().endswith(".svg"):
        return None
    async with session.get(url, max_redirects=10) as response:
        if response.status != 200:
            return None
        data = await response.read()
    try:
        return decode_image_bytes(data)
    except (UnidentifiedImageError, OSError, ValueError):
        return None
