# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One owned Linux cleansing root, with separate readiness IPC and bounded shutdown."""

import asyncio
import logging
import math
import os
import sys

import psutil
from nexent.storage.errors import CapabilityUnsupported, InvalidInput, Unavailable

READY = b"R"
_POSIX = os.name == "posix"
logger = logging.getLogger(__name__)


async def _read_ready(descriptor):
    loop = asyncio.get_running_loop()
    result = loop.create_future()
    os.set_blocking(descriptor, False)

    def read():
        if result.done():
            return
        try:
            value = os.read(descriptor, 1)
        except BlockingIOError:
            return
        except OSError:
            result.set_exception(Unavailable())
            return
        if value == READY:
            result.set_result(None)
        else:
            result.set_exception(Unavailable())

    loop.add_reader(descriptor, read)
    try:
        await result
    finally:
        loop.remove_reader(descriptor)


def _children(pid):
    try:
        return psutil.Process(pid).children(recursive=True)
    except psutil.NoSuchProcess:
        return []


class CleanseProcess:
    def __init__(self, *, startup_seconds=30, shutdown_seconds=15):
        if any(
            type(value) not in {int, float}
            or not math.isfinite(value)
            or not 0 < value <= 60
            for value in (startup_seconds, shutdown_seconds)
        ):
            raise InvalidInput()
        self.startup_seconds, self.shutdown_seconds = startup_seconds, shutdown_seconds
        self.process = None
        self._stopped = False

    async def start(self):
        if not _POSIX:
            raise CapabilityUnsupported()
        if self.process is not None:
            raise InvalidInput()
        read_fd, write_fd = os.pipe()
        try:
            try:
                async with asyncio.timeout(self.startup_seconds):
                    self.process = await asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "management.services.file.cleanse_root",
                        "--ready-fd",
                        str(write_fd),
                        pass_fds=(write_fd,),
                        start_new_session=True,
                    )
                    os.close(write_fd)
                    write_fd = None
                    await _read_ready(read_fd)
            except TimeoutError:
                logger.warning(
                    "cleanse_root_start_timeout pid=%s phase=ready threshold_seconds=%s exception_type=TimeoutError",
                    self.process.pid if self.process is not None else None, self.startup_seconds,
                )
                await self.stop()
                raise
            except BaseException:
                await self.stop()
                raise
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)

    async def wait(self):
        if self.process is None:
            raise InvalidInput()
        return await self.process.wait()

    async def stop(self):
        if self.process is None or self._stopped:
            return
        descendants = {child.pid: child for child in _children(self.process.pid)}
        if self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
        try:
            async with asyncio.timeout(self.shutdown_seconds):
                await self.process.wait()
        except TimeoutError:
            logger.warning(
                "cleanse_root_stop_timeout pid=%s phase=terminate threshold_seconds=%s exception_type=TimeoutError",
                self.process.pid, self.shutdown_seconds,
            )
            # Parser attempts own separate sessions; a root-only kill misses them.
            descendants.update(
                {child.pid: child for child in _children(self.process.pid)}
            )
            for child in reversed(tuple(descendants.values())):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            if self.process.returncode is None:
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass
            async with asyncio.timeout(5):
                await self.process.wait()
        self._stopped = True
