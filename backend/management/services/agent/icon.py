# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Image rules and storage orchestration for agent and repository icons."""

from io import BytesIO
from time import monotonic
from uuid import uuid4

from nexent.storage.errors import StorageError
from nexent.storage.models import ObjectRef, OperationContext

from infrastructure.file_reads import file_read_ports
from infrastructure.icon_objects import icon_write_port

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
    content_type = validate_icon_image(content)
    context = OperationContext(f'icon-write-{uuid4().hex}', monotonic() + 5)
    try:
        with icon_write_port(object_name, context=context) as store, BytesIO(content) as stream:
            store.put(ObjectRef('files', object_name), stream, content_type=content_type,
                      size=len(content), context=context)
    except StorageError as error:
        raise ValueError(f"Failed to upload icon: {error}") from error
    return content_type


def read_icon_image(object_name: str) -> tuple[bytes, str]:
    context = OperationContext(f'icon-read-{uuid4().hex}', monotonic() + 5)
    content = bytearray()
    try:
        with (
            file_read_ports(object_name, context=context) as store,
            store.open_read(ObjectRef('files', object_name), context=context) as reader,
        ):
            while len(content) <= ICON_MAX_BYTES:
                block = reader.read(min(64 * 1024, ICON_MAX_BYTES + 1 - len(content)))
                if not block:
                    break
                content.extend(block)
    except StorageError as error:
        raise FileNotFoundError("Icon not found") from error
    try:
        payload = bytes(content)
        return payload, validate_icon_image(payload)
    except ValueError as exc:
        raise FileNotFoundError("Icon is invalid") from exc
