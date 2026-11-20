# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""FILE-BODY-04 preserves full-read downloads and cancels on disconnect."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_download_returns_complete_bytes_and_releases_disconnect_listener(mocker):
    from management.services.file import download

    stopped = asyncio.Event()
    async def receive():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    stream = SimpleNamespace(read_all=AsyncMock(return_value=b'complete'), aclose=AsyncMock())
    open_read = mocker.patch.object(download, 'open_object_stream', new_callable=AsyncMock, return_value=stream)
    assert await download.read_download('attachments/owner/a.txt', SimpleNamespace(receive=receive)) == (b'complete', 'text/plain')
    open_read.assert_awaited_once_with('attachments/owner/a.txt')
    stream.aclose.assert_awaited_once()
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_preview_closes_a_reader_opened_as_the_client_disconnects(mocker):
    from management.services.file import download

    opened = asyncio.Event()
    stream = SimpleNamespace(aclose=AsyncMock())

    async def open_read(*args):
        opened.set()
        return stream

    async def receive():
        await opened.wait()
        return {'type': 'http.disconnect'}

    mocker.patch.object(download, 'open_object_stream', side_effect=open_read)
    with pytest.raises(asyncio.CancelledError):
        await download.open_preview('attachments/owner/a.pdf', SimpleNamespace(receive=receive), 2, 4)
    stream.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_cancels_read_and_closes_before_return(mocker):
    from management.services.file import download

    entered = asyncio.Event()
    async def blocked():
        entered.set()
        await asyncio.Event().wait()
    async def receive():
        await entered.wait()
        return {'type': 'http.disconnect'}
    stream = SimpleNamespace(read_all=AsyncMock(side_effect=blocked), aclose=AsyncMock())
    mocker.patch.object(download, 'open_object_stream', new_callable=AsyncMock, return_value=stream)
    with pytest.raises(asyncio.CancelledError):
        await download.read_download('attachments/owner/a.txt', SimpleNamespace(receive=receive))
    stream.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_provider_failure_cannot_return_a_partial_download(mocker):
    from management.services.file import download
    from nexent.storage.errors import Unavailable

    stream = SimpleNamespace(read_all=AsyncMock(side_effect=Unavailable()), aclose=AsyncMock())
    mocker.patch.object(download, 'open_object_stream', new_callable=AsyncMock, return_value=stream)
    async def receive():
        await asyncio.Event().wait()
    with pytest.raises(Unavailable):
        await download.read_download('attachments/owner/a.txt', SimpleNamespace(receive=receive))
    stream.aclose.assert_awaited_once()
