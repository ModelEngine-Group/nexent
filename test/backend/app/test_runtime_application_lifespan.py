# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Runtime application lifecycle owns configuration and dependent task shutdown."""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


class RecordingApp:
    def __init__(self, lifespan):
        self.lifespan = lifespan
        self.state = SimpleNamespace(thread_manager=None)
        self.middleware = []
        self.routers = []
        self.get_routes = []

    def add_middleware(self, middleware):
        self.middleware.append(middleware)

    def include_router(self, router):
        self.routers.append(router)

    def get(self, path, **_kwargs):
        def register(handler):
            self.get_routes.append((path, handler))
            return handler

        return register


class RuntimeThreadManager:
    def __init__(self):
        self.state = "created"
        self.started = False
        self.shutdown = AsyncMock()

    def start(self):
        self.started = True
        self.state = "running"

    async def run(self, _lane, _spec, function, *args, **kwargs):
        return function(*args, **kwargs)

    def snapshot(self):
        return {"service_name": "runtime", "active_count": 0}


@pytest.mark.parametrize("recovery_mode", ["startup", "maintenance"])
def test_runtime_lifespan_owns_configuration_recovery_and_shutdown(monkeypatch, recovery_mode):
    start_configuration = AsyncMock()
    stop_configuration = AsyncMock()
    monkeypatch.setitem(
        sys.modules,
        "infrastructure.system_configuration.runtime",
        _module(
            "infrastructure.system_configuration.runtime",
            start_system_configuration=start_configuration,
            stop_system_configuration=stop_configuration,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "contracts.constants.environment",
        _module(
            "contracts.constants.environment", RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS=1,
            NEXENT_RECOVERY_MODE=recovery_mode, NEXENT_MAINTENANCE_EPOCH="maintenance-batch",
        ),
    )
    manager = RuntimeThreadManager()
    shutdown_streams = AsyncMock(return_value=[])
    monkeypatch.setitem(
        sys.modules,
        "runtime.thread_management",
        _module("runtime.thread_management", runtime_thread_manager=manager,
                shutdown_agent_stream_tasks=shutdown_streams),
    )

    for name, attribute in (
        ("runtime.agentos.memory", "create_memory_store_router"),
        ("runtime.agentos.model", "create_model_router"),
        ("runtime.agentos.model_administration", "create_model_administration_router"),
        ("runtime.agentos.prepared_run", "create_prepared_run_router"),
        ("runtime.agentos.resume", "create_run_lifecycle_router"),
        ("runtime.agentos.ephemeral", "create_ephemeral_run_router"),
        ("runtime.agentos.evaluation", "create_evaluation_router"),
        ("runtime.model.service", "ModelService"),
        ("runtime.agentos.middleware", "AgentOSMiddleware"),
        ("runtime.agentos.debug", "stop_agentos_debug"),
        ("runtime.api.voice.streaming", "voice_runtime_router"),
        ("runtime.api.sandbox", "router"),
        ("infrastructure.model_adapter", "get_adapter_from_config"),
    ):
        monkeypatch.setitem(sys.modules, name, _module(name, **{attribute: MagicMock()}))

    recover_models = MagicMock()
    verify_maintenance = MagicMock()
    initialize_sandbox = MagicMock(return_value=None)
    monkeypatch.setitem(
        sys.modules, "infrastructure.rdb.runtime_maintenance",
        _module("infrastructure.rdb.runtime_maintenance", require_completed_runtime_maintenance=verify_maintenance),
    )
    monkeypatch.setitem(
        sys.modules, "runtime.sandbox_runtime",
        _module("runtime.sandbox_runtime", initialize_sandbox_coordination=initialize_sandbox),
    )
    monkeypatch.setitem(
        sys.modules,
        "infrastructure.rdb.model_records",
        _module("infrastructure.rdb.model_records", fail_detecting_models_on_startup=recover_models,
                get_model_by_model_id=MagicMock()),
    )

    runtime_state = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "infrastructure.redis.run_state",
        _module("infrastructure.redis.run_state", runtime_state_service=runtime_state),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.http.server.app_factory",
        _module("backend.http.server.app_factory", create_app=lambda **kwargs: RecordingApp(kwargs["lifespan"])),
    )
    monkeypatch.setitem(
        sys.modules,
        "runtime.api.exception_handler",
        _module("runtime.api.exception_handler", ExceptionHandlerMiddleware=object),
    )
    manager_state = SimpleNamespace(CREATED="created")
    set_default = MagicMock()
    clear_default = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "nexent.core.concurrency",
        _module(
            "nexent.core.concurrency",
            ManagedTaskSpec=lambda *args, **kwargs: SimpleNamespace(**kwargs),
            ManagedThreadSpec=lambda **kwargs: SimpleNamespace(**kwargs),
            ManagerState=manager_state,
            set_default_thread_manager=set_default,
            clear_default_thread_manager=clear_default,
        ),
    )

    trajectory_processor = MagicMock()
    conversation_deleted = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "infrastructure.trace.bootstrap",
        _module(
            "infrastructure.trace.bootstrap",
            local_trajectory_processor=trajectory_processor,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "infrastructure.trace.trajectory_runtime",
        _module(
            "infrastructure.trace.trajectory_runtime",
            conversation_deleted=conversation_deleted,
        ),
    )

    recover = MagicMock()
    watch = AsyncMock()
    monkeypatch.setitem(
        sys.modules,
        "runtime.recovery",
        _module("runtime.recovery", recover_streaming_runs=recover, watch_executions=watch),
    )
    cleanup = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "runtime.workspace_cleanup",
        _module("runtime.workspace_cleanup", cleanup_orphaned_agent_workspaces=cleanup),
    )
    monkeypatch.setitem(
        sys.modules,
        "nexent.core.agents.sandbox.execution",
        _module("nexent.core.agents.sandbox.execution", SandboxPoolManager=SimpleNamespace(_instance=None)),
    )

    module_path = BACKEND_DIR / "runtime" / "api" / "application.py"
    spec = importlib.util.spec_from_file_location("isolated_runtime_application", module_path)
    application = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(application)

    shutdown_order = MagicMock()
    shutdown_order.attach_mock(shutdown_streams, "agents")
    shutdown_order.attach_mock(trajectory_processor.shutdown, "trajectory")
    shutdown_order.attach_mock(stop_configuration, "configuration")
    shutdown_order.attach_mock(manager.shutdown, "thread_manager")

    async def exercise():
        async with application.runtime_lifespan(None):
            pass

    asyncio.run(exercise())

    assert manager.started
    set_default.assert_called_once_with(manager)
    runtime_state.set_thread_manager.assert_called_once_with(manager)
    start_configuration.assert_awaited_once()
    configuration_io = start_configuration.call_args.args[0]
    assert asyncio.run(configuration_io(lambda: "loaded")) == "loaded"
    trajectory_processor.start.assert_called_once()
    assert trajectory_processor.start.call_args.args[0] is manager
    assert (
        trajectory_processor.deleted_conversation_check is conversation_deleted
    )
    trajectory_processor.request_stop.assert_called_once_with()
    trajectory_processor.shutdown.assert_called_once_with()
    initialize_sandbox.assert_called_once_with(manager)
    if recovery_mode == "maintenance":
        verify_maintenance.assert_called_once_with("maintenance-batch")
        recover_models.assert_not_called()
        recover.assert_not_called()
        cleanup.assert_not_called()
    else:
        verify_maintenance.assert_not_called()
        recover_models.assert_called_once_with()
        recover.assert_called_once_with()
        cleanup.assert_called_once_with()
    shutdown_streams.assert_awaited_once()
    assert 0 <= shutdown_streams.await_args.kwargs["timeout"] <= 1
    stop_configuration.assert_awaited_once_with()
    manager.shutdown.assert_awaited_once()
    assert 0 <= manager.shutdown.await_args.kwargs["timeout"] <= 1
    assert [call[0] for call in shutdown_order.mock_calls] == [
        "agents", "trajectory", "configuration", "thread_manager",
    ]
    clear_default.assert_called_once_with(manager)
