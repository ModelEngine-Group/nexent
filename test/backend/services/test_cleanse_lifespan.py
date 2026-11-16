# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management owns one independent root and reports terminal background failures."""

import asyncio
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from management.services.file.cleanse_lifespan import cleanse_lifespan
from nexent.storage.errors import InvalidInput


@pytest.mark.asyncio
async def test_disabled_lifespan_does_not_construct_process():
    factory = MagicMock()
    app = SimpleNamespace(state=SimpleNamespace())
    async with cleanse_lifespan(app, enabled=False, factory=factory):
        assert not hasattr(app.state, "cleanse_root")
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_normal_exit_stops_one_root_and_preserves_other_background_tasks():
    process = MagicMock(start=AsyncMock(), stop=AsyncMock())
    done = asyncio.Event()
    process.wait = AsyncMock(side_effect=done.wait)
    factory = MagicMock(return_value=process)
    other = object()
    app = SimpleNamespace(state=SimpleNamespace(required_background_tasks=(other,)))
    async with cleanse_lifespan(app, enabled=True, factory=factory):
        monitor = app.state.required_background_tasks[-1]
        assert app.state.cleanse_root is process and not monitor.done()
        await asyncio.sleep(0)
    assert monitor.cancelled()
    process.start.assert_awaited_once()
    process.stop.assert_awaited_once()
    factory.assert_called_once()
    assert app.state.required_background_tasks == (other,)


@pytest.mark.asyncio
async def test_unexpected_exit_finishes_health_monitor_without_restart(caplog):
    process = MagicMock(
        start=AsyncMock(), stop=AsyncMock(), wait=AsyncMock(return_value=3)
    )
    factory = MagicMock(return_value=process)
    app = SimpleNamespace(state=SimpleNamespace())
    async with cleanse_lifespan(app, enabled=True, factory=factory):
        monitor = app.state.required_background_tasks[-1]
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert monitor.done() and isinstance(monitor.exception(), RuntimeError)
        assert "cleanse_root_exited" in caplog.text
    factory.assert_called_once()
    process.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_failure_never_installs_a_successful_monitor():
    process = MagicMock(start=AsyncMock(side_effect=RuntimeError("fixture")))
    app = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(RuntimeError, match="fixture"):
        async with cleanse_lifespan(app, enabled=True, factory=lambda: process):
            pytest.fail("failed startup yielded")
    assert not getattr(app.state, "required_background_tasks", ())


@pytest.mark.asyncio
async def test_body_failure_still_stops_the_owned_root():
    process = MagicMock(start=AsyncMock(), stop=AsyncMock())
    process.wait = AsyncMock(side_effect=asyncio.Event().wait)
    app = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(ValueError, match="body"):
        async with cleanse_lifespan(app, enabled=True, factory=lambda: process):
            raise ValueError("body")
    process.stop.assert_awaited_once()
    assert not app.state.required_background_tasks


@pytest.mark.parametrize(
    "value,expected", [("false", "False"), ("true", "True"), ("invalid", None)]
)
def test_environment_flag_is_strict_and_explicit(value, expected):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from contracts.constants.environment import MANAGEMENT_FILE_CLEANSE_ENABLED; print(MANAGEMENT_FILE_CLEANSE_ENABLED)",
        ],
        env={**os.environ, "MANAGEMENT_FILE_CLEANSE_ENABLED": value},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if expected is None:
        assert result.returncode != 0
        assert "MANAGEMENT_FILE_CLEANSE_ENABLED must be true or false" in result.stderr
    else:
        assert result.returncode == 0 and result.stdout.strip() == expected


@pytest.mark.asyncio
async def test_invalid_enabled_argument_does_not_construct_process():
    factory = MagicMock()
    app = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(InvalidInput):
        async with cleanse_lifespan(app, enabled="false", factory=factory):
            pytest.fail("invalid flag yielded")
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_monitor_error_still_stops_owned_process():
    process = MagicMock(start=AsyncMock(), stop=AsyncMock(), wait=AsyncMock(side_effect=OSError("fixture")))
    app = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(OSError, match="fixture"):
        async with cleanse_lifespan(app, enabled=True, factory=lambda: process):
            await asyncio.sleep(0)
    process.stop.assert_awaited_once()
    assert not app.state.required_background_tasks
