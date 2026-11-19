# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Saved imports need managed workers even when capture and source reads are off."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from ops import lifespan


@pytest.mark.asyncio
async def test_saved_import_workers_exist_without_capture_or_read_service(monkeypatch):
    manager = Mock(shutdown=AsyncMock())
    workers = Mock()
    monkeypatch.setattr(lifespan, "create_thread_manager", lambda: manager)
    monkeypatch.setattr(lifespan, "create_trajectory_workers", workers)
    monkeypatch.setattr(lifespan.config, "TRAJECTORY_READ_ENABLED", False)
    monkeypatch.setattr(lifespan.config, "MONITORING_PROVIDER", "otlp")
    app = FastAPI()
    async with lifespan.ops_lifespan(app):
        assert app.state.thread_manager is manager
        manager.start.assert_called_once()
        workers.assert_not_called()
        assert app.state.ready
    manager.shutdown.assert_awaited_once()
    assert not app.state.ready
