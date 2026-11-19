# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Runtime application lifecycle owns configuration and dependent task shutdown."""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


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


def test_runtime_lifespan_owns_configuration_scheduler_and_shutdown(monkeypatch):
    start_configuration = AsyncMock()
    stop_configuration = AsyncMock()
    monkeypatch.setitem(
        sys.modules,
        "management.configuration.runtime",
        _module(
            "management.configuration.runtime",
            start_system_configuration=start_configuration,
            stop_system_configuration=stop_configuration,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "contracts.constants.environment",
        _module("contracts.constants.environment", RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS=1),
    )
    manager = RuntimeThreadManager()
    monkeypatch.setitem(
        sys.modules,
        "runtime.thread_management",
        _module("runtime.thread_management", runtime_thread_manager=manager),
    )

    automation = _module("management.api.automation.agent_automation")
    automation.conversation_automation_router = object()
    automation.router = object()
    monkeypatch.setitem(sys.modules, automation.__name__, automation)
    for name, attribute in (
        ("management.api.conversation.conversation_management", "router"),
        ("management.api.conversation.conversation_share", "router"),
        ("management.api.conversation.workbench_pins", "router"),
        ("runtime.api.agent.execution", "agent_runtime_router"),
        ("runtime.api.evaluation.execution", "router"),
        ("runtime.api.file.upload", "file_management_runtime_router"),
        ("runtime.api.skill.creation", "skill_creator_router"),
        ("runtime.api.voice.streaming", "voice_runtime_router"),
    ):
        monkeypatch.setitem(sys.modules, name, _module(name, **{attribute: object()}))

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
    monkeypatch.setitem(
        sys.modules,
        "management.recovery",
        _module("management.recovery", recover_runtime_tasks=recover),
    )
    scheduler = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    monkeypatch.setitem(
        sys.modules,
        "management.services.automation.scheduler",
        _module("management.services.automation.scheduler", agent_automation_scheduler=scheduler),
    )
    cleanup = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "management.services.agent.workspace_cleanup",
        _module("management.services.agent.workspace_cleanup", cleanup_orphaned_agent_workspaces=cleanup),
    )
    shutdown_streams = AsyncMock(return_value=[])
    monkeypatch.setitem(
        sys.modules,
        "management.services.agent.execution",
        _module("management.services.agent.execution", shutdown_agent_stream_tasks=shutdown_streams),
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
    scheduler.start.assert_awaited_once_with()
    cleanup.assert_called_once_with()
    scheduler.stop.assert_awaited_once_with()
    shutdown_streams.assert_awaited_once()
    assert 0 <= shutdown_streams.await_args.kwargs["timeout"] <= 1
    stop_configuration.assert_awaited_once_with()
    manager.shutdown.assert_awaited_once()
    assert 0 <= manager.shutdown.await_args.kwargs["timeout"] <= 1
    clear_default.assert_called_once_with(manager)
