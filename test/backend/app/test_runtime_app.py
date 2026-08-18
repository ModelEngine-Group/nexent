"""Tests for Runtime application startup and shutdown."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.apps import runtime_app
from consts.exceptions import DistributedStateUnavailable
from services.agent_automation import scheduler as scheduler_module


@pytest.mark.asyncio
async def test_runtime_lifespan_checks_redis_before_starting_scheduler(monkeypatch):
    """Runtime starts the scheduler only after the required Redis check passes."""
    events = []
    runtime_state = MagicMock()
    runtime_state.ping_async = AsyncMock(side_effect=lambda: events.append("ping"))
    scheduler = MagicMock()
    scheduler.start = AsyncMock(side_effect=lambda: events.append("start"))
    scheduler.stop = AsyncMock(side_effect=lambda: events.append("stop"))
    monkeypatch.setattr(runtime_app, "runtime_state_service", runtime_state)
    monkeypatch.setattr(scheduler_module, "agent_automation_scheduler", scheduler)

    async with runtime_app.runtime_lifespan(runtime_app.app):
        events.append("ready")

    assert events == ["ping", "start", "ready", "stop"]


@pytest.mark.asyncio
async def test_runtime_lifespan_rejects_redis_failure(monkeypatch):
    """A failed Redis PING prevents scheduler startup and application readiness."""
    runtime_state = MagicMock()
    runtime_state.ping_async = AsyncMock(
        side_effect=DistributedStateUnavailable("redis down")
    )
    scheduler = MagicMock()
    scheduler.start = AsyncMock()
    scheduler.stop = AsyncMock()
    monkeypatch.setattr(runtime_app, "runtime_state_service", runtime_state)
    monkeypatch.setattr(scheduler_module, "agent_automation_scheduler", scheduler)

    with pytest.raises(DistributedStateUnavailable, match="redis down"):
        async with runtime_app.runtime_lifespan(runtime_app.app):
            pass

    scheduler.start.assert_not_awaited()
    scheduler.stop.assert_not_awaited()
