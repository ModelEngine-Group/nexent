# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Root startup and shutdown use one owned process and finite deadlines."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from nexent.storage.errors import CapabilityUnsupported, Unavailable

from infrastructure.file_processing import root_process


@pytest.fixture
def child(mocker):
    exited = asyncio.Event()
    process = MagicMock(pid=123, returncode=None)

    async def wait():
        await exited.wait()
        return process.returncode

    def terminate():
        process.returncode = 0
        exited.set()

    process.wait = AsyncMock(side_effect=wait)
    process.terminate.side_effect = terminate
    process.kill.side_effect = terminate
    mocker.patch.object(root_process, "_POSIX", True)
    spawn = mocker.patch.object(
        root_process.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(return_value=process),
    )
    ready = mocker.patch.object(root_process, "_read_ready", new=AsyncMock())
    mocker.patch.object(root_process, "_children", return_value=[])
    return process, spawn, ready


@pytest.mark.asyncio
async def test_start_waits_for_dedicated_pipe_and_closes_descriptors(child):
    process, spawn, ready = child
    owner = root_process.CleanseProcess()
    await owner.start()
    ready.assert_awaited_once()
    descriptor = ready.call_args.args[0]
    with pytest.raises(OSError):
        os.fstat(descriptor)
    args = spawn.call_args.args
    assert args[1:3] == ("-m", "management.services.file.cleanse_root")
    assert spawn.call_args.kwargs["pass_fds"]
    assert spawn.call_args.kwargs["start_new_session"] is True
    await owner.stop()
    await owner.stop()
    spawn.assert_awaited_once()
    process.terminate.assert_called_once()
    process.kill.assert_not_called()


@pytest.mark.asyncio
async def test_failed_handshake_reclaims_child_without_restart(child):
    process, spawn, ready = child
    ready.side_effect = Unavailable()
    owner = root_process.CleanseProcess()
    with pytest.raises(Unavailable):
        await owner.start()
    process.terminate.assert_called_once()
    spawn.assert_awaited_once()


@pytest.mark.asyncio
async def test_ready_deadline_stops_the_owned_process_once(child, caplog):
    process, spawn, ready = child

    async def stall(*args):
        await asyncio.Event().wait()

    ready.side_effect = stall
    owner = root_process.CleanseProcess(startup_seconds=0.01)
    with pytest.raises(TimeoutError):
        await owner.start()
    process.terminate.assert_called_once()
    spawn.assert_awaited_once()
    assert "cleanse_root_start_timeout" in caplog.text
    assert not any(row.levelname == "ERROR" for row in caplog.records)


@pytest.mark.asyncio
async def test_stop_deadline_reclaims_only_owned_descendants_once(
    child, mocker, caplog
):
    process, spawn, _ = child
    own = MagicMock(pid=456)
    unowned = MagicMock(pid=789)
    mocker.patch.object(root_process, "_children", return_value=[own])
    process.terminate.side_effect = None
    owner = root_process.CleanseProcess(shutdown_seconds=0.01)
    await owner.start()
    await owner.stop()
    own.kill.assert_called_once()
    unowned.kill.assert_not_called()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    spawn.assert_awaited_once()
    assert "cleanse_root_stop_timeout" in caplog.text
    assert not any(row.levelname == "ERROR" for row in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [b"R", b"X", b""])
async def test_readiness_protocol_checks_the_actual_pipe_byte(mocker, value):
    loop = asyncio.get_running_loop()
    # Windows UT substitutes only the Linux nonblocking-descriptor setup.
    mocker.patch.object(root_process.os, "set_blocking", create=True)
    read_fd, write_fd = os.pipe()
    os.write(write_fd, value)
    os.close(write_fd)
    added = mocker.patch.object(
        loop, "add_reader", side_effect=lambda descriptor, callback: callback()
    )
    removed = mocker.patch.object(loop, "remove_reader")
    try:
        if value == b"R":
            await root_process._read_ready(read_fd)
        else:
            with pytest.raises(Unavailable):
                await root_process._read_ready(read_fd)
    finally:
        os.close(read_fd)
    added.assert_called_once()
    removed.assert_called_once_with(read_fd)


@pytest.mark.asyncio
async def test_unsupported_platform_never_spawns(child, mocker):
    _, spawn, _ = child
    mocker.patch.object(root_process, "_POSIX", False)
    with pytest.raises(CapabilityUnsupported):
        await root_process.CleanseProcess().start()
    spawn.assert_not_called()
