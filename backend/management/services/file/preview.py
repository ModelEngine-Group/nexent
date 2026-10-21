# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Stable object keys shared by preview creation and source cleanup."""

import hashlib
import logging

logger = logging.getLogger("file_management_service")


def build_preview_pdf_object_key(object_name: str, *, temporary: bool = False) -> str:
    """Keep cached and in-progress previews in the existing MinIO namespaces."""
    stem = object_name.rsplit(".", 1)[0] if "." in object_name else object_name
    suffix = hashlib.md5(object_name.encode()).hexdigest()[:8]
    directory = "converting" if temporary else "converted"
    extension = "pdf.tmp" if temporary else "pdf"
    return f"preview/{directory}/{stem}_{suffix}.{extension}"

from consts.const import DATA_PROCESS_SERVICE
from consts.const import FILE_PREVIEW_SIZE_LIMIT
from contracts.exceptions import FileTooLargeException
from contracts.exceptions import NotFoundException
from consts.const import OFFICE_MIME_TYPES
from contracts.exceptions import OfficeConversionException
from typing import Optional
from typing import Tuple
from contracts.exceptions import UnsupportedFileTypeException
import asyncio
from management.db.file.attachment import copy_file
from management.db.file.attachment import delete_file
from management.db.file.attachment import file_exists
from management.db.file.attachment import get_content_type
from management.db.file.attachment import get_file_range
from management.db.file.attachment import get_file_size_from_minio
from management.db.file.attachment import get_file_stream_raw
import httpx

_conversion_locks: dict[str, asyncio.Lock] = {}


_conversion_locks_guard = asyncio.Lock()


async def resolve_preview_file(object_name: str) -> Tuple[str, str, int]:
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
        'text/plain',
        'text/csv',
        'text/markdown',
        'application/json',
    }
    if (
        content_type == 'application/pdf'
        or content_type.startswith('image/')
        or content_type in direct_preview_types
    ):
        return object_name, content_type, file_size

    # Office documents - convert to PDF with caching
    elif content_type in OFFICE_MIME_TYPES:
        pdf_object_name = build_preview_pdf_object_key(object_name)
        temp_pdf_object_name = build_preview_pdf_object_key(object_name, temporary=True)

        # Trigger conversion if cache is missing or corrupted
        if not _is_pdf_cache_valid(pdf_object_name):
            await _convert_office_to_cached_pdf(object_name, pdf_object_name, temp_pdf_object_name)

        pdf_size = get_file_size_from_minio(pdf_object_name)
        return pdf_object_name, 'application/pdf', pdf_size

    # Unsupported file type
    else:
        raise UnsupportedFileTypeException(
            f"Unsupported file type for preview: {content_type}")


def get_preview_stream(actual_object_name: str, start: Optional[int] = None, end: Optional[int] = None):
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
        raise NotFoundException(
            "File not found or failed to read from storage")
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
            f"Corrupted cache detected (cannot read), deleting: {pdf_object_name}")
        delete_file(pdf_object_name)
        return False

    close_fn = getattr(stream, "close", None)
    if callable(close_fn):
        try:
            close_fn()
        except Exception as e:
            logger.warning(
                f"Failed to close cache probe stream for {pdf_object_name}: {str(e)}")

    return True


async def _convert_office_to_cached_pdf(
    object_name: str,
    pdf_object_name: str,
    temp_pdf_object_name: str,
) -> None:
    """
    Convert an Office document to PDF and store the result in MinIO.

    Args:
        object_name: Source Office file path in MinIO
        pdf_object_name: Final cached PDF path in MinIO
        temp_pdf_object_name: Temporary PDF path used during conversion
    """
    # Get or create a lock for this specific file to prevent duplicate conversions
    async with _conversion_locks_guard:
        if object_name not in _conversion_locks:
            _conversion_locks[object_name] = asyncio.Lock()
        file_lock = _conversion_locks[object_name]

    try:
        async with file_lock:
            # Double-check: another request may have completed the conversion while we waited
            if _is_pdf_cache_valid(pdf_object_name):
                return

            # Conversion semaphore is enforced inside the data-process service
            try:
                # Request conversion: data-process downloads, converts, uploads to temp path, validates
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{DATA_PROCESS_SERVICE}/tasks/convert_to_pdf",
                        data={
                            "object_name": object_name,
                            "pdf_object_name": temp_pdf_object_name,
                        },
                    )
                if response.status_code != 200:
                    logger.error(
                        "Office conversion failed with non-200 response: object=%s, status=%s, body=%s",
                        object_name,
                        response.status_code,
                        response.text,
                    )
                    raise RuntimeError(
                        f"Conversion service returned status {response.status_code}"
                    )

                # Atomic move from temp to final location, then clean up temp
                copy_result = copy_file(
                    source_object=temp_pdf_object_name, dest_object=pdf_object_name)
                if not copy_result.get('success'):
                    logger.error(
                        "Failed to finalize converted PDF cache: object=%s, temp=%s, dest=%s, error=%s",
                        object_name,
                        temp_pdf_object_name,
                        pdf_object_name,
                        copy_result.get('error', 'Unknown error'),
                    )
                    raise RuntimeError(
                        "Failed to finalize converted PDF cache")
                delete_file(temp_pdf_object_name)

            except Exception as e:
                if file_exists(temp_pdf_object_name):
                    delete_file(temp_pdf_object_name)
                logger.error(f"Office conversion failed: {str(e)}")
                if isinstance(e, OfficeConversionException):
                    raise
                raise OfficeConversionException(
                    "Office file conversion failed") from e
    finally:
        # Clean up the file lock (prevents memory leak for many unique files)
        async with _conversion_locks_guard:
            _conversion_locks.pop(object_name, None)
