# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""External web-image reads; object storage is deliberately a different capability."""

from io import BytesIO
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError


async def load_web_image(session, url: str) -> Image.Image | None:
    if urlsplit(url).scheme.lower() not in {"http", "https"} or url.lower().endswith(".svg"):
        return None
    async with session.get(url, max_redirects=10) as response:
        if response.status != 200:
            return None
        data = await response.read()
    with BytesIO(data) as buffer:
        try:
            image = Image.open(buffer)
        except (UnidentifiedImageError, OSError):
            return None
        try:
            image.load()
        except (OSError, ValueError):
            image.close()
            return None
        return image
