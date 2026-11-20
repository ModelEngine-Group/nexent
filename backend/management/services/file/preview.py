# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from contracts.file_types import get_content_type

"""Management prepares previews through SI with one bounded conversion budget."""

import asyncio
import hashlib
import logging
from threading import Event
from time import monotonic
from uuid import uuid4
from weakref import WeakValueDictionary

from contracts.constants.constants import FILE_PREVIEW_SIZE_LIMIT, OFFICE_MIME_TYPES
from contracts.errors.exceptions import (
    FileTooLargeException,
    OfficeConversionException,
    UnsupportedFileTypeException,
)
from management.services.file.office_preview import convert_preview
from management.services.file.preview_storage import PreviewObjects
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

logger = logging.getLogger('file_management_service')
_conversion_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_conversion_locks_guard = asyncio.Lock()


def build_preview_pdf_object_key(object_name: str) -> str:
    stem = object_name.rsplit('.', 1)[0] if '.' in object_name else object_name
    suffix = hashlib.md5(object_name.encode()).hexdigest()[:8]
    return f'preview/converted/{stem}_{suffix}.pdf'


async def _io(phase, action, *args, context):
    context.remaining()
    return await run_blocking('file-preview-' + phase, action, *args, context=context,
                              lane='control-io', owner='management.file.preview')


async def _is_pdf_cache_valid(name, *, context):
    return await _io('cache', PreviewObjects().cache_valid, name, context=context)


async def _resolve(object_name, *, context):
    objects = PreviewObjects()
    file_size = await _io('source-stat', objects.size, object_name, context=context)
    if file_size > FILE_PREVIEW_SIZE_LIMIT:
        raise FileTooLargeException(f'File size {file_size} bytes exceeds the {FILE_PREVIEW_SIZE_LIMIT // (1024 * 1024)} MB preview limit')
    content_type = get_content_type(object_name)
    if (content_type == 'application/pdf' or content_type.startswith('image/')
        or content_type in {'text/plain', 'text/csv', 'text/markdown', 'application/json'}):
        return object_name, content_type, file_size
    if content_type not in OFFICE_MIME_TYPES:
        raise UnsupportedFileTypeException(f'Unsupported file type for preview: {content_type}')
    cache = build_preview_pdf_object_key(object_name)
    if not await _is_pdf_cache_valid(cache, context=context):
        await _convert_office_to_cached_pdf(object_name, cache, context=context)
    size = await _io('cache-stat', objects.size, cache, context=context)
    return cache, 'application/pdf', size


async def resolve_preview_file(object_name: str) -> tuple[str, str, int]:
    cancelled = Event()
    context = OperationContext('file-preview-' + uuid4().hex, monotonic()+120, cancelled=cancelled)
    try:
        async with asyncio.timeout(context.remaining()):
            return await _resolve(object_name, context=context)
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('file_preview_timeout operation_id=%s phase=prepare threshold_seconds=120 exception_type=%s',
                       context.operation_id, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        cancelled.set()


async def _convert_office_to_cached_pdf(object_name, pdf_object_name, *, context):
    async with _conversion_locks_guard:
        file_lock = _conversion_locks.get(object_name)
        if file_lock is None:
            file_lock = asyncio.Lock()
            _conversion_locks[object_name] = file_lock
    async with file_lock:
        context.remaining()
        if await _is_pdf_cache_valid(pdf_object_name, context=context):
            return
        try:
            await convert_preview(object_name, pdf_object_name, timeout=context.remaining())
        except (DeadlineExceeded, TimeoutError, OfficeConversionException):
            raise
        except Exception as error:
            logger.warning('office_preview_failed error_type=%s', type(error).__name__)
            raise OfficeConversionException('Office file conversion failed') from error
