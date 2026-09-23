"""Image validation and object storage shared by agent and repository icons."""

import io

ICON_MAX_BYTES = 2 * 1024 * 1024


def validate_icon_image(content: bytes) -> str:
    if not content:
        raise ValueError("Icon file is empty")
    if len(content) > ICON_MAX_BYTES:
        raise ValueError("Icon must not exceed 2 MB")

    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("Icon must be a PNG, JPEG, GIF, or WebP image")


def upload_icon_image(content: bytes, object_name: str) -> str:
    from database.client import minio_client

    content_type = validate_icon_image(content)
    success, error = minio_client.upload_fileobj(io.BytesIO(content), object_name)
    if not success:
        raise ValueError(f"Failed to upload icon: {error}")
    return content_type


def read_icon_image(object_name: str) -> tuple[bytes, str]:
    from database.attachment_db import get_file_stream

    stream = get_file_stream(object_name)
    if stream is None:
        raise FileNotFoundError("Icon not found")
    content = stream.read()
    try:
        return content, validate_icon_image(content)
    except ValueError as exc:
        raise FileNotFoundError("Icon is invalid") from exc
