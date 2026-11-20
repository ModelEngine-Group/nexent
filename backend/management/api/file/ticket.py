# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Redeem a download ticket through StorageInterface and the owned file stream."""

from http import HTTPStatus
from time import monotonic
from uuid import uuid4

from contracts.constants import environment
from contracts.errors.exceptions import NotFoundException
from contracts.object_tickets import InvalidObjectTicket, open_object_ticket
from fastapi import HTTPException
from management.api.file.http import (
    ObjectStreamingResponse,
    _parse_range_header,
    build_content_disposition_header,
)
from management.services.file.download import open_preview
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, NotFound, StorageError
from nexent.storage.models import ObjectRef, OperationContext

from infrastructure.file_reads import file_read_ports


def _stat_download(key):
    context = OperationContext(f'file-ticket-stat-{uuid4().hex}', monotonic() + 5)
    with file_read_ports(key, context=context) as store:
        return store.stat(ObjectRef('files', key), context=context)


async def download_ticket_response(ticket, request):
    try:
        key = open_object_ticket(ticket, secret=environment.JWT_SECRET)
    except InvalidObjectTicket:
        raise HTTPException(HTTPStatus.FORBIDDEN, 'Invalid or expired file ticket') from None
    return await download_authorized_object_response(key, request)


async def download_authorized_object_response(key, request):
    try:
        meta = await run_blocking('file-ticket-stat', _stat_download, key, lane='control-io', owner='management.file')
        headers = {
            'Accept-Ranges': 'bytes',
            'Content-Disposition': build_content_disposition_header(key.rsplit('/', 1)[-1]),
            'Content-Length': str(meta.size),
        }
        status, start, end = HTTPStatus.OK, None, None
        if value := request.headers.get('range'):
            selection = _parse_range_header(value, meta.size)
            if selection is None:
                raise HTTPException(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, 'Range not satisfiable',
                                    headers={'Content-Range': f'bytes */{meta.size}'})
            start, end = selection
            status = HTTPStatus.PARTIAL_CONTENT
            headers['Content-Range'] = f'bytes {start}-{end}/{meta.size}'
            headers['Content-Length'] = str(end - start + 1)
        stream = await open_preview(key, request, start, end, version=meta.ref.version)
    except (NotFound, NotFoundException):
        raise HTTPException(HTTPStatus.BAD_GATEWAY, 'Failed to fetch file from storage, status: 404') from None
    except DeadlineExceeded:
        raise HTTPException(HTTPStatus.GATEWAY_TIMEOUT, 'Timeout fetching file from storage') from None
    except StorageError:
        raise HTTPException(HTTPStatus.BAD_GATEWAY, 'Failed to fetch file from storage') from None
    return ObjectStreamingResponse(stream, status_code=status, headers=headers, media_type=meta.content_type)
