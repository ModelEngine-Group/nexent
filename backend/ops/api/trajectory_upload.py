# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bound multipart uploads before Starlette can spool an unbounded file."""

import asyncio

from ops.services.trajectory.primitives import QueryError
from starlette.formparsers import MultiPartException, MultiPartParser


async def read_archive_form(request, max_bytes, seconds):
    async def bounded():
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_bytes + 64 * 1024:
                raise MultiPartException("archive_too_large")
            yield chunk

    parser = MultiPartParser(request.headers, bounded(), max_files=1, max_fields=0)
    try:
        async with asyncio.timeout(seconds):
            form = await parser.parse()
        values = list(form.multi_items())
        if (
            len(values) != 1
            or values[0][0] != "file"
            or not hasattr(values[0][1], "file")
        ):
            await form.close()
            raise QueryError("invalid_archive", 422)
        upload = values[0][1]
        if upload.size > max_bytes:
            await form.close()
            raise QueryError("archive_too_large", 413)
        return form, upload
    except BaseException as error:
        # Starlette only closes these on MultiPartException; cancellation also owns them.
        for file in parser._files_to_close_on_error:
            file.close()
        if isinstance(error, MultiPartException):
            raise QueryError(
                "archive_too_large"
                if error.message == "archive_too_large"
                else "invalid_archive",
                413 if error.message == "archive_too_large" else 422,
            ) from error
        if isinstance(error, TimeoutError):
            raise QueryError("archive_upload_timeout", 503) from error
        raise
