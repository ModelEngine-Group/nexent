# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prove query ownership and independent operations resource lifetimes."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_runtime_has_no_query_routes_or_projection_workers():
    source = (ROOT / "backend/runtime/api/application.py").read_text()
    assert "trajectory_router" not in source
    assert "SummaryWorker" not in source
    assert "StatisticsWorker" not in source
    assert "ops." not in source
    assert "local_trajectory_processor.start(" in source


def test_query_implementations_belong_to_operations():
    assert (ROOT / "backend/ops/api/trajectory.py").is_file()
    assert (ROOT / "backend/ops/db/trajectory/queries.py").is_file()
    assert not (ROOT / "backend/management/services/trajectory").exists()
    assert not (ROOT / "backend/management/api/observability/trajectory.py").exists()
    source = (
        ROOT / "backend/infrastructure/observability/trajectory_runtime.py"
    ).read_text()
    assert "ops." not in source
    assert "maintenance_store=maintenance" not in source


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "start", "body", "stop"])
async def test_ops_trajectory_lifecycle_releases_manager(monkeypatch, failure):
    from ops import lifespan

    manager = Mock(shutdown=AsyncMock())
    workers = Mock(stop=AsyncMock())
    monkeypatch.setattr(lifespan, "trajectory_enabled", lambda: True)
    monkeypatch.setattr(lifespan, "create_thread_manager", lambda: manager)
    monkeypatch.setattr(lifespan, "create_trajectory_workers", lambda: workers)
    if failure == "start":
        workers.start.side_effect = RuntimeError("controlled start")
    elif failure == "stop":
        workers.stop.side_effect = RuntimeError("controlled stop")
    app = SimpleNamespace(state=SimpleNamespace(ready=False))

    async def exercise():
        async with lifespan.ops_lifespan(app):
            assert app.state.ready is True
            assert app.state.thread_manager is manager
            if failure == "body":
                raise RuntimeError("controlled body")

    if failure:
        with pytest.raises(RuntimeError, match="controlled"):
            await exercise()
    else:
        await exercise()
    assert app.state.ready is False
    manager.start.assert_called_once()
    workers.stop.assert_awaited_once_with(manager)
    manager.shutdown.assert_awaited_once()


def test_query_lanes_are_owned_by_ops():
    from ops.concurrency import create_thread_manager

    manager = create_thread_manager()
    assert manager.service_name == "ops"
    source = ast.parse((ROOT / "backend/infrastructure/concurrency.py").read_text())
    runtime = next(
        n
        for n in source.body
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "runtime_thread_manager"
            for t in n.targets
        )
    )
    assert "trajectory-read" not in ast.unparse(runtime)
    assert "trajectory-cleanup" not in ast.unparse(runtime)


@pytest.mark.parametrize("role,expected", [("ADMIN", 200), ("USER", 403), ("", 401)])
def test_enabled_ops_serves_private_queries_on_existing_api_prefix(
    monkeypatch, role, expected
):
    from contracts.constants import environment as config
    from fastapi.testclient import TestClient
    from ops import lifespan
    from ops.api import trajectory
    from ops.api.application import create_app
    from ops.concurrency import create_thread_manager

    monkeypatch.setattr(config, "TRAJECTORY_READ_ENABLED", True)
    manager = create_thread_manager()
    workers = Mock(stop=AsyncMock())
    monkeypatch.setattr(lifespan, "create_thread_manager", lambda: manager)
    monkeypatch.setattr(lifespan, "create_trajectory_workers", lambda: workers)
    monkeypatch.setattr(
        trajectory,
        "get_current_user_context",
        lambda auth: (
            "admin" if role else None,
            "tenant",
            role,
        ),
    )
    service = Mock()
    monkeypatch.setattr(trajectory, "get_service", lambda: service)
    records = Mock(return_value={"items": [], "total": 0})
    monkeypatch.setattr(trajectory, "records", records)
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/trajectory/records" in paths
    assert "/conversation/agent_groups" in paths
    assert "/agent/run" not in paths
    with TestClient(app) as client:
        response = client.get("/api/trajectory/records")
        assert response.status_code == expected
        assert response.headers["cache-control"] == "private,no-store"
        if expected == 200:
            assert response.json()["data"] == {"items": [], "total": 0}
            assert records.call_args.args[0] is service
            assert records.call_args.args[1].tenant_id == "tenant"
        else:
            records.assert_not_called()
        invalid = client.get(
            "/api/trajectory/conversations/123/snapshot?trajectory_id=x&limit=0"
        )
        assert invalid.status_code == 422
        assert invalid.headers["cache-control"] == "private,no-store"
    assert manager.state.value == "closed"


def test_runtime_capture_has_no_periodic_maintenance(tmp_path, mocker):
    from contracts.constants import environment as config
    from infrastructure.observability.trajectory_runtime import create_local_processor

    mocker.patch("management.db.trajectory.repository.ExecutionRepository")
    settings = SimpleNamespace(
        **{name: getattr(config, name) for name in dir(config) if name.isupper()}
    )
    settings.MONITORING_PROVIDER = "local_file"
    settings.TRAJECTORY_ROOT_DIR = str(tmp_path)
    processor = create_local_processor(settings, lambda: None)
    assert processor._maintenance_store is None
    assert processor._cleanup_interval_provider is None


@pytest.mark.asyncio
async def test_workers_register_maintenance_and_projections_in_ops_manager(mocker):
    from ops.services.trajectory import lifecycle

    processor = Mock()
    summary, statistics = Mock(), Mock()
    mocker.patch.object(
        lifecycle, "create_maintenance_processor", return_value=processor
    )
    mocker.patch.object(lifecycle, "ExecutionRepository")
    mocker.patch.object(lifecycle, "SummaryWorker", return_value=summary)
    mocker.patch.object(lifecycle, "StatisticsWorker", return_value=statistics)
    manager = Mock(run=AsyncMock())
    manager.register_service.side_effect = [
        SimpleNamespace(execution_id="summary"),
        SimpleNamespace(execution_id="statistics"),
    ]
    workers = lifecycle.TrajectoryWorkers()
    workers.start(manager)
    processor.start.assert_called_once()
    assert processor.start.call_args.args[0] is manager
    specs = [call.args[0] for call in manager.register_service.call_args_list]
    assert [spec.task_name for spec in specs] == [
        "trajectory-summary-compensation",
        "trajectory-statistics-refresh",
    ]
    assert [call.args[0] for call in manager.start_service.call_args_list] == [
        "summary",
        "statistics",
    ]
    await workers.stop(manager)
    summary.request_stop.assert_called_once()
    statistics.request_stop.assert_called_once()
    processor.request_stop.assert_called_once()
    assert manager.run.await_args.args[2] == processor.shutdown
