# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Pure image serialization shared by service adapters."""

import base64
from io import BytesIO

from PIL import Image


def encode_image_bytes(data: bytes) -> dict:
    """Preserve RGB source format and the established white-matte JPEG projection."""
    with BytesIO(data) as source, Image.open(source) as original:
        original.load()
        image = original
        try:
            if original.mode == "RGBA":
                image = Image.new("RGB", original.size, (255, 255, 255))
                with original.getchannel("A") as alpha:
                    image.paste(original, mask=alpha)
            elif original.mode != "RGB":
                image = original.convert("RGB")
            format_name = image.format or "JPEG"
            with BytesIO() as output:
                image.save(output, format=format_name)
                return {
                    "success": True,
                    "base64": base64.b64encode(output.getvalue()).decode("utf-8"),
                    "content_type": "image/" + format_name.lower(),
                }
        finally:
            if image is not original:
                image.close()
