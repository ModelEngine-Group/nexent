# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Check file and request limits and cleanup at the multipart parser boundary."""

import asyncio
from tempfile import SpooledTemporaryFile
from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from ops.api.trajectory_upload import read_archive_form
from ops.services.trajectory.primitives import QueryError


def multipart_request(stream):
    return SimpleNamespace(
        headers=Headers({"content-type": "multipart/form-data; boundary=archive"}),
        stream=stream,
    )


def upload(body, *, finished=True):
    data = (
        b'--archive\r\nContent-Disposition: form-data; name="file"; filename="capture.zip"\r\n'
        b"\r\n" + body
    )
    return data + b"\r\n--archive--\r\n" if finished else data


@pytest.fixture
def spooled_files(mocker):
    files = []

    def open_file(**kwargs):
        file = SpooledTemporaryFile(**kwargs)
        files.append(file)
        return file

    mocker.patch("starlette.formparsers.SpooledTemporaryFile", side_effect=open_file)
    yield files
    for file in files:
        file.close()


@pytest.mark.parametrize("size,accepted", [(16, True), (17, False), (65553, False)])
async def test_enforces_payload_and_wire_limits(size, accepted, spooled_files):
    async def stream():
        data = upload(b"a" * size)
        yield data[:128]
        yield data[128:]

    if accepted:
        form, file = await read_archive_form(multipart_request(stream), 16, 2)
        try:
            assert await file.read() == b"a" * size
            assert file.filename == "capture.zip"
        finally:
            await form.close()
    else:
        with pytest.raises(QueryError) as failure:
            await read_archive_form(multipart_request(stream), 16, 2)
        assert (failure.value.code, failure.value.status) == ("archive_too_large", 413)
    (file,) = spooled_files
    assert file.closed


async def test_empty_multipart_is_not_an_archive():
    async def stream():
        yield b"--archive--\r\n"

    with pytest.raises(QueryError) as failure:
        await read_archive_form(multipart_request(stream), 16, 2)
    assert (failure.value.code, failure.value.status) == ("invalid_archive", 422)


@pytest.mark.parametrize("cancel", [False, True])
async def test_partial_file_is_closed_on_timeout_or_cancellation(cancel, spooled_files):
    paused = asyncio.Event()

    async def stream():
        yield upload(b"payload", finished=False)
        paused.set()
        await asyncio.Future()

    async with asyncio.timeout(2):
        if cancel:
            task = asyncio.create_task(read_archive_form(multipart_request(stream), 16, 2))
            await paused.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(QueryError) as failure:
                await read_archive_form(multipart_request(stream), 16, 0)
            assert (failure.value.code, failure.value.status) == ("archive_upload_timeout", 503)
    (file,) = spooled_files
    assert file.closed
