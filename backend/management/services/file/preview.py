# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Stable object keys shared by preview creation and source cleanup."""

import hashlib
import logging

logger = logging.getLogger("file_management_service")


def build_preview_pdf_object_key(object_name: str) -> str:
    """Keep the public cache key stable; conversion attempts use unique keys."""
    stem = object_name.rsplit(".", 1)[0] if "." in object_name else object_name
    suffix = hashlib.md5(object_name.encode()).hexdigest()[:8]
    return f"preview/converted/{stem}_{suffix}.pdf"


import asyncio
from weakref import WeakValueDictionary

from contracts.constants.constants import FILE_PREVIEW_SIZE_LIMIT, OFFICE_MIME_TYPES
from contracts.errors.exceptions import (
    FileTooLargeException,
    NotFoundException,
    OfficeConversionException,
    UnsupportedFileTypeException,
)
from management.db.file.attachment import (
    delete_file,
    file_exists,
    get_content_type,
    get_file_range,
    get_file_size_from_minio,
    get_file_stream_raw,
)
from management.services.file.office_preview import convert_preview

_conversion_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


_conversion_locks_guard = asyncio.Lock()


async def resolve_preview_file(object_name: str) -> tuple[str, str, int]:
    """
    Resolve the actual object name, content type, and total size for preview.

    Args:
        object_name: File object name in storage

    Returns:
        Tuple[str, str, int]: (actual_object_name, content_type, total_size)
    """
    if not file_exists(object_name):
        raise NotFoundException(f"File not found: {object_name}")

    file_size = get_file_size_from_minio(object_name)
    if file_size > FILE_PREVIEW_SIZE_LIMIT:
        raise FileTooLargeException(
            f"File size {file_size} bytes exceeds the {FILE_PREVIEW_SIZE_LIMIT // (1024 * 1024)} MB preview limit"
        )

    content_type = get_content_type(object_name)

    # PDF, images, and directly readable text files - return directly
    direct_preview_types = {
        "text/plain",
        "text/csv",
        "text/markdown",
        "application/json",
    }
    if (
        content_type == "application/pdf"
        or content_type.startswith("image/")
        or content_type in direct_preview_types
    ):
        return object_name, content_type, file_size

    # Office documents - convert to PDF with caching
    elif content_type in OFFICE_MIME_TYPES:
        pdf_object_name = build_preview_pdf_object_key(object_name)

        # Trigger conversion if cache is missing or corrupted
        if not _is_pdf_cache_valid(pdf_object_name):
            await _convert_office_to_cached_pdf(object_name, pdf_object_name)

        pdf_size = get_file_size_from_minio(pdf_object_name)
        return pdf_object_name, "application/pdf", pdf_size

    # Unsupported file type
    else:
        raise UnsupportedFileTypeException(
            f"Unsupported file type for preview: {content_type}"
        )


def get_preview_stream(
    actual_object_name: str, start: int | None = None, end: int | None = None
):
    """
    Fetch a preview stream for the given object, optionally limited to a byte range.

    Args:
        actual_object_name: Resolved object name (after Office conversion if needed)
        start: Start byte offset (inclusive). Must be provided together with end.
        end: End byte offset (inclusive), matching HTTP Range semantics.

    Returns:
        Raw boto3 Body stream
    """
    if (start is None) != (end is None):
        raise ValueError("start and end must be provided together")

    if start is None:
        stream = get_file_stream_raw(actual_object_name)
    else:
        stream = get_file_range(actual_object_name, start, end)

    if stream is None:
        raise NotFoundException("File not found or failed to read from storage")
    return stream


def _is_pdf_cache_valid(pdf_object_name: str) -> bool:
    """
    Check whether a cached PDF exists and is readable.
    """
    if not file_exists(pdf_object_name):
        return False

    # Verify the cached file is readable by fetching a small range
    stream = get_file_range(pdf_object_name, 0, 0)
    if stream is None:
        logger.warning(
            f"Corrupted cache detected (cannot read), deleting: {pdf_object_name}"
        )
        delete_file(pdf_object_name)
        return False

    close_fn = getattr(stream, "close", None)
    if callable(close_fn):
        try:
            close_fn()
        except Exception as e:  # noqa: BLE001 - Cleanup must not hide a valid cache probe.
            logger.warning(
                f"Failed to close cache probe stream for {pdf_object_name}: {e!s}"
            )

    return True


async def _convert_office_to_cached_pdf(
    object_name: str,
    pdf_object_name: str,
) -> None:
    """
    Convert an Office document to PDF and store the result in MinIO.

    Args:
        object_name: Source Office file path in MinIO
        pdf_object_name: Final cached PDF path in MinIO
    """
    # Get or create a lock for this specific file to prevent duplicate conversions
    async with _conversion_locks_guard:
        file_lock = _conversion_locks.get(object_name)
        if file_lock is None:
            file_lock = asyncio.Lock()
            _conversion_locks[object_name] = file_lock

    async with file_lock:
        if _is_pdf_cache_valid(pdf_object_name):
            return
        try:
            await convert_preview(object_name, pdf_object_name)
        except OfficeConversionException:
            raise
        except Exception as error:
            logger.warning("office_preview_failed error_type=%s", type(error).__name__)
            raise OfficeConversionException("Office file conversion failed") from error
