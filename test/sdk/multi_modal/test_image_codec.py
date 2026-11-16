# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Image serialization preserves the established proxy representation."""

import base64
from io import BytesIO

import pytest
from nexent.multi_modal.image_codec import encode_image_bytes
from PIL import Image, UnidentifiedImageError


@pytest.mark.parametrize("mode,expected", [("RGB", "PNG"), ("RGBA", "JPEG"), ("P", "JPEG"), ("L", "JPEG")])
def test_encoding_format_and_white_background(mode, expected):
    with Image.new(mode, (8, 8)) as image, BytesIO() as source:
        image.save(source, format="PNG")
        result = encode_image_bytes(source.getvalue())
    assert set(result) == {"success", "base64", "content_type"}
    assert result["success"] is True
    assert result["content_type"] == "image/" + expected.lower()
    with Image.open(BytesIO(base64.b64decode(result["base64"]))) as decoded:
        assert decoded.format == expected
        assert decoded.mode == "RGB"
        if mode == "RGBA":
            assert decoded.getpixel((0, 0)) == (255, 255, 255)


def test_invalid_image_is_not_encoded():
    with pytest.raises(UnidentifiedImageError):
        encode_image_bytes(b"not an image")
