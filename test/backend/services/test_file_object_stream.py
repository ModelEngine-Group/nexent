# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""FILE-BODY-01/02 proves bounded managed ownership without external providers."""

import asyncio
from contextlib import contextmanager
from queue import Queue
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.errors.exceptions import ManagementReadBusyError, NotFoundException
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.storage.errors import DeadlineExceeded, NotFound, Unavailable
from nexent.storage.models import ByteRange


class Reader:
    def __init__(self, data=b'owned', *, blocked=False, error=None):
        self.data, self.blocked, self.error = data, blocked, error
        self.reads, self.closed_count = [], 0
        self.release, self.entered, self.lock = Event(), Event(), Lock()

    def read(self, size):
        self.entered.set()
        self.reads.append(size)
        if self.blocked:
            self.release.wait(2)
        if self.error:
            raise self.error
        with self.lock:
            if self.closed_count:
                raise Unavailable()
            value, self.data = self.data[:size], self.data[size:]
            return value

    def close(self):
        with self.lock:
            if self.closed_count:
                return
            self.closed_count += 1
        self.release.set()


@pytest.fixture
async def manager():
    manager = ThreadManager('owned-file-read', {'file-stream': LanePolicy('file-stream', 1, 1,
        queue_timeout_seconds=.05, cancel_grace_seconds=.2, shutdown_grace_seconds=1)})
    manager.start()
    try:
        yield manager
    finally:
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids


@pytest.fixture
def source():
    reader = Reader()
    opened, closed = [], []
    @contextmanager
    def ports(name, *, context):
        opened.append(name)
        @contextmanager
        def read(ref, *, byte_range=None, context):
            opened.append(byte_range)
            try:
                yield reader
            finally:
                reader.close()
        try:
            yield SimpleNamespace(open_read=read)
        finally:
            closed.append(name)
    return SimpleNamespace(reader=reader, ports=ports, opened=opened, closed=closed)


@pytest.mark.asyncio
async def test_complete_bytes_are_bounded_and_close_once(manager, source):
    from management.services.file.streaming import open_object_stream

    source.reader.data = b'x' * (64*1024*4+7)
    stream = await open_object_stream('knowledge_base/owned.pdf', manager=manager, ports=source.ports)
    assert await stream.read_all() == b'x' * (64*1024*4+7)
    await stream.aclose()
    assert set(source.reader.reads) == {64*1024} and source.reader.closed_count == 1
    assert source.closed == ['knowledge_base/owned.pdf']
    assert manager.snapshot().active_count == 0


@pytest.mark.asyncio
async def test_final_chunk_is_drained_when_producer_finishes_during_eof_check(manager, source, mocker):
    from management.services.file.streaming import ObjectStream

    stream = ObjectStream('knowledge_base/owned.pdf', None, manager, source.ports, 1)
    stream.queue = Queue(maxsize=2)
    future = mocker.Mock()

    def finish():
        stream.queue.put_nowait(b'last chunk')
        future.done.side_effect = None
        future.done.return_value = True
        return True

    future.done.side_effect = finish
    stream.execution = SimpleNamespace(future=future)
    mocker.patch.object(stream, 'aclose', new_callable=AsyncMock)

    assert await stream.read_all() == b'last chunk'
    future.result.assert_called_once_with()


@pytest.mark.asyncio
async def test_range_uses_exclusive_si_end(manager, source):
    from management.services.file.streaming import open_object_stream

    stream = await open_object_stream('knowledge_base/owned.pdf', 2, 4, manager=manager, ports=source.ports)
    await stream.read_all()
    assert source.opened == ['knowledge_base/owned.pdf', ByteRange(2, 5)]


@pytest.mark.asyncio
async def test_partial_range_arguments_never_open_storage(manager, source):
    from management.services.file.streaming import open_object_stream

    with pytest.raises(ValueError, match='provided together'):
        await open_object_stream('knowledge_base/owned.pdf', start=0, manager=manager, ports=source.ports)
    assert not source.opened


@pytest.mark.asyncio
async def test_response_send_failure_still_closes_the_producer(manager, source):
    from management.api.file.http import ObjectStreamingResponse
    from management.services.file.streaming import open_object_stream
    from starlette.requests import ClientDisconnect

    source.reader.data = b'x' * (64*1024*10)
    stream = await open_object_stream('knowledge_base/owned.pdf', manager=manager, ports=source.ports)
    async def send(message):
        raise OSError('owned client disconnected')
    async def receive():
        await asyncio.Event().wait()
    with pytest.raises(ClientDisconnect):
        await ObjectStreamingResponse(stream)({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send)
    assert source.reader.closed_count == 1 and manager.snapshot().active_count == 0


@pytest.mark.asyncio
async def test_cancel_unblocks_active_read_and_drains_owner(manager, source):
    from management.services.file.streaming import open_object_stream

    source.reader.blocked = True
    stream = await open_object_stream('knowledge_base/owned.pdf', manager=manager, ports=source.ports)
    await stream.aclose()
    assert source.reader.closed_count == 1 and len(source.closed) == 1
    assert manager.snapshot().active_count == 0


@pytest.mark.asyncio
async def test_root_timeout_closes_and_logs_once(manager, source, caplog):
    from management.services.file.streaming import open_object_stream

    source.reader.blocked = True
    stream = await open_object_stream('knowledge_base/owned.pdf', manager=manager, ports=source.ports, timeout=.05)
    with pytest.raises(DeadlineExceeded):
        await stream.read_all()
    assert source.reader.closed_count == 1 and manager.snapshot().active_count == 0
    assert len([r for r in caplog.records if r.levelname == 'WARNING' and 'file_stream_timeout' in r.message]) == 1
    assert not [r for r in caplog.records if r.levelname == 'ERROR']


@pytest.mark.asyncio
async def test_backpressure_is_bounded_and_terminates_without_consumer(manager, source):
    from management.services.file.streaming import open_object_stream

    source.reader.data = b'x' * (64*1024*10)
    stream = await open_object_stream('knowledge_base/owned.pdf', manager=manager, ports=source.ports, timeout=.05)
    with pytest.raises(DeadlineExceeded):
        await asyncio.wait_for(asyncio.wrap_future(stream.execution.future), timeout=1)
    assert stream.buffered_chunks <= 2 and len(source.reader.reads) <= 3
    await stream.aclose()
    assert source.reader.closed_count == 1 and manager.snapshot().active_count == 0


@pytest.mark.asyncio
async def test_saturated_lane_never_opens_another_store(manager, source):
    from management.services.file.streaming import open_object_stream

    source.reader.blocked = True
    first = await open_object_stream('knowledge_base/owned.pdf', manager=manager, ports=source.ports)
    second = asyncio.create_task(open_object_stream('never-queued', manager=manager, ports=source.ports))
    await asyncio.sleep(0)
    try:
        with pytest.raises(ManagementReadBusyError):
            await open_object_stream('never-admitted', manager=manager, ports=source.ports)
        with pytest.raises(ManagementReadBusyError):
            await second
    finally:
        await first.aclose()
    assert source.opened == ['knowledge_base/owned.pdf', None]


@pytest.mark.asyncio
@pytest.mark.parametrize(('error', 'expected'), [(NotFound(), NotFoundException), (Unavailable(), Unavailable)])
async def test_open_errors_remain_distinct_without_probe_or_retry(manager, error, expected):
    from management.services.file.streaming import open_object_stream

    attempts = []
    @contextmanager
    def ports(name, *, context):
        attempts.append(name)
        raise error
        yield
    with pytest.raises(expected):
        await open_object_stream('knowledge_base/owned.pdf', manager=manager, ports=ports)
    assert attempts == ['knowledge_base/owned.pdf'] and manager.snapshot().active_count == 0
