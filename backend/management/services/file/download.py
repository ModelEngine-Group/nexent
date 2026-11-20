# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Complete existing download reads before responding, with owned disconnect cleanup."""

import asyncio

import anyio
from contracts.file_types import get_content_type
from management.services.file.streaming import CHUNK_SIZE, open_object_stream


async def _while_connected(request, operation):
    async def disconnected():
        while (await request.receive())['type'] != 'http.disconnect':
            pass

    reader = asyncio.create_task(operation, name='file-read-consumer')
    listener = asyncio.create_task(disconnected(), name='file-download-disconnect')
    try:
        done, _ = await asyncio.wait((reader, listener), return_when=asyncio.FIRST_COMPLETED)
        if listener in done:
            listener.result()
            raise asyncio.CancelledError()
        return reader.result()
    finally:
        for task in (reader, listener):
            if not task.done():
                task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(reader, listener, return_exceptions=True)


async def read_download(object_name, request):
    async def read():
        stream = await open_object_stream(object_name)
        try:
            return await stream.read_all(), get_content_type(object_name)
        finally:
            await stream.aclose()
    return await _while_connected(request, read())


async def open_preview(object_name, request, start=None, end=None):
    stream = None
    async def open_read():
        nonlocal stream
        stream = await open_object_stream(object_name, start, end)
        return stream
    try:
        return await _while_connected(request, open_read())
    except BaseException:
        # A simultaneous disconnect and completed open must not orphan its reader.
        if stream is not None:
            await stream.aclose()
        raise


async def byte_chunks(data):
    for position in range(0, len(data), CHUNK_SIZE):
        yield data[position:position+CHUNK_SIZE]
