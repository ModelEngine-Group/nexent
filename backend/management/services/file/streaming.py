# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One managed producer owns an SI reader and bounded bytes until consumption ends."""

import asyncio
import logging
from queue import Empty, Full, Queue
from threading import Lock
from time import monotonic
from uuid import uuid4

import anyio
from contracts.constants.environment import (
    MANAGEMENT_FILE_STREAM_TIMEOUT_SECONDS,
    RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
)
from contracts.errors.exceptions import ManagementReadBusyError, NotFoundException
from nexent.core.concurrency import (
    ManagedTaskSpec,
    ThreadCapacityExceeded,
    ThreadQueueTimedOut,
    get_current_thread_manager,
    get_default_thread_manager,
)
from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.storage.errors import (
    DeadlineExceeded,
    NotFound,
    OperationCancelled,
    Unavailable,
)
from nexent.storage.models import ByteRange, ObjectRef, OperationContext

from infrastructure.file_reads import file_read_ports

logger = logging.getLogger(__name__)
CHUNK_SIZE = 64 * 1024


class ObjectStream:
    def __init__(self, name, byte_range, manager, ports, timeout, version=None):
        self.name, self.byte_range, self.manager, self.ports = name, byte_range, manager, ports
        self.version = version
        self.timeout = timeout
        self.scope = RunCancellationScope()
        self.context = OperationContext('file-stream-' + uuid4().hex, monotonic()+timeout, cancelled=self.scope.stop_event)
        self.loop = asyncio.get_running_loop()
        self.ready, self.data_ready = asyncio.Event(), asyncio.Event()
        self.queue, self.execution, self.opened = None, None, False
        self.phase = 'open'
        self._warned, self._warn_lock = False, Lock()
        self._closed = False

    @property
    def buffered_chunks(self):
        return self.queue.qsize() if self.queue is not None else 0

    def _notify(self, event):
        if not self.loop.is_closed():
            self.loop.call_soon_threadsafe(event.set)

    def cancel(self):
        self.scope.cancel()
        if self.queue is not None:
            while True:
                try:
                    self.queue.get_nowait()
                except Empty:
                    break
        self._notify(self.ready)
        self._notify(self.data_ready)

    def _timeout(self, error):
        with self._warn_lock:
            if self._warned:
                return
            self._warned = True
        threshold = self.timeout if monotonic() >= self.context.deadline else min(5, self.timeout)
        logger.warning('file_stream_timeout operation_id=%s phase=%s threshold_seconds=%s exception_type=%s',
                       self.context.operation_id, self.phase, threshold, type(error).__name__)

    def _produce(self):
        self.context.remaining()
        # Only the admitted worker creates a data channel or opens storage.
        self.queue = Queue(maxsize=2)
        try:
            with (
                self.ports(self.name, context=self.context) as store,
                store.open_read(ObjectRef('files', self.name, self.version), byte_range=self.byte_range,
                                context=self.context) as reader,
            ):
                token = self.scope.register_closer(reader.close)
                try:
                    self.context.remaining()
                    self.opened = True
                    self._notify(self.ready)
                    while True:
                        self.context.remaining()
                        self.phase = 'read'
                        block = reader.read(CHUNK_SIZE)
                        self.context.remaining()
                        if block == b'':
                            return
                        if not isinstance(block, bytes):
                            raise Unavailable(operation_id=self.context.operation_id)
                        self.phase = 'backpressure'
                        try:
                            self.queue.put(block, timeout=self.context.remaining())
                        except Full:
                            raise DeadlineExceeded(operation_id=self.context.operation_id) from None
                        self.context.remaining()
                        self._notify(self.data_ready)
                finally:
                    self.scope.unregister_closer(token)
        except Exception as error:
            # Close-induced transport errors after cancellation are cancellation outcomes.
            if self.scope.stop_event.is_set():
                raise OperationCancelled(operation_id=self.context.operation_id) from None
            if isinstance(error, DeadlineExceeded) or monotonic() >= self.context.deadline:
                self._timeout(error)
                if not isinstance(error, DeadlineExceeded):
                    raise DeadlineExceeded(operation_id=self.context.operation_id) from error
            raise

    async def start(self):
        spec = ManagedTaskSpec(task_name='file-object-read', owner='management.file',
                               deadline_monotonic=self.context.deadline, close_hook=self.cancel)
        try:
            self.execution = self.manager.submit('file-stream', spec, self._produce)
            self.execution.future.add_done_callback(lambda _: (self._notify(self.ready), self._notify(self.data_ready)))
            async with asyncio.timeout_at(self.context.deadline):
                await self.manager.wait_until_started(self.execution)
                await self.ready.wait()
                self.context.remaining()
                if not self.opened:
                    self.execution.future.result()
            return self
        except ThreadCapacityExceeded as error:
            await self.aclose()
            raise ManagementReadBusyError() from error
        except ThreadQueueTimedOut as error:
            await self.aclose()
            raise ManagementReadBusyError(queue_timeout_seconds=error.timeout_seconds) from error
        except NotFound as error:
            await self.aclose()
            raise NotFoundException('Storage object does not exist') from error
        except (TimeoutError, DeadlineExceeded) as error:
            self._timeout(error)
            await self.aclose()
            raise DeadlineExceeded(operation_id=self.context.operation_id) from error
        except BaseException:
            await self.aclose()
            raise

    async def chunks(self):
        try:
            async with asyncio.timeout_at(self.context.deadline):
                while True:
                    self.context.remaining()
                    self.data_ready.clear()
                    # Once the producer is done, an empty queue is a stable EOF.
                    # Check completion first so a final chunk cannot slip between the checks.
                    producer_done = self.execution.future.done()
                    try:
                        value = self.queue.get_nowait()
                    except Empty:
                        if producer_done:
                            self.execution.future.result()
                            return
                        await self.data_ready.wait()
                        continue
                    yield value
        except (TimeoutError, DeadlineExceeded) as error:
            self._timeout(error)
            raise DeadlineExceeded(operation_id=self.context.operation_id) from error
        finally:
            await self.aclose()

    def __aiter__(self):
        return self.chunks()

    async def read_all(self):
        return b''.join([block async for block in self.chunks()])

    async def aclose(self):
        if self._closed:
            return
        self._closed = True
        self.cancel()
        if self.execution is None:
            return
        future = self.execution.future
        if not future.done():
            self.manager.cancel(self.execution.execution_id, reason='file consumer closed',
                                wait_timeout=0, mark_stuck_on_timeout=False)
        with anyio.CancelScope(shield=True):
            try:
                await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)),
                                       timeout=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
            except asyncio.CancelledError:
                if not future.cancelled():
                    raise
            except TimeoutError:
                logger.error('file_stream_close_stuck operation_id=%s', self.context.operation_id)
                self.manager.cancel(self.execution.execution_id, reason='file close grace exceeded', wait_timeout=0)
                raise RuntimeError('File reader did not stop within its close grace') from None
            except Exception:  # noqa: BLE001 - The open/consumer path already owns this future's original error.
                # The open/consumer path owns the original error; cleanup does not replace it.
                return


async def open_object_stream(name, start=None, end=None, *, manager=None, ports=file_read_ports, timeout=None, version=None):
    if (start is None) != (end is None):
        raise ValueError('start and end must be provided together')
    manager = manager or get_current_thread_manager() or get_default_thread_manager()
    if manager is None:
        raise RuntimeError('File reads require a service-owned ThreadManager')
    byte_range = None if start is None else ByteRange(start, end+1)
    return await ObjectStream(name, byte_range, manager, ports,
        MANAGEMENT_FILE_STREAM_TIMEOUT_SECONDS if timeout is None else timeout, version=version).start()
