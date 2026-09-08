"""Unit tests for the Celery-prefork data-process service entrypoint."""

import importlib.util
import signal
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def service_module(monkeypatch):
    uvicorn = types.ModuleType("uvicorn")
    uvicorn.run = MagicMock()
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = MagicMock()
    fastapi = types.ModuleType("fastapi")

    class FakeFastAPI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.routers = []

        def include_router(self, router):
            self.routers.append(router)

    fastapi.FastAPI = FakeFastAPI
    logging_utils = types.ModuleType("utils.logging_utils")
    logging_utils.configure_logging = MagicMock()
    logging_utils.get_uvicorn_logging_config = MagicMock(return_value={})
    constants = types.ModuleType("consts.const")
    constants.REDIS_URL = "redis://test:6379/0"
    constants.REDIS_BACKEND_URL = "redis://test:6379/1"
    constants.REDIS_PORT = 6379
    constants.FLOWER_PORT = 5555
    constants.DISABLE_CELERY_FLOWER = False
    constants.DOCKER_ENVIRONMENT = False
    constants.DP_PARSE_MAX_PROCESSES = 3
    constants.DP_PARSE_MIN_PROCESSES = 1
    constants.DP_PARSE_THREADS_PER_PROCESS = 2
    constants.DP_PARSE_MAX_TASKS_PER_CHILD = 1000
    constants.DP_PRELOAD_MODELS = "unstructured_default"
    constants.DP_PARSER_STARTUP_TIMEOUT_S = 1

    for name, module in {
        "uvicorn": uvicorn,
        "dotenv": dotenv,
        "fastapi": fastapi,
        "utils.logging_utils": logging_utils,
        "consts.const": constants,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    module_name = "backend.data_process_service"
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path(__file__).parents[2] / "backend" / "data_process_service.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.object(signal, "signal"):
        spec.loader.exec_module(module)
    return module


def test_worker_configs_use_prefork_for_parser_and_threads_for_other_stages(service_module):
    configs = service_module.ServiceManager._build_worker_configs(4)

    assert configs[0]["queue"] == "parse_q"
    assert configs[0]["pool"] == "prefork"
    assert configs[0]["concurrency"] == 3
    assert configs[0]["min_processes"] == 1
    assert configs[0]["max_tasks_per_child"] == 1000
    assert all(config["pool"] == "threads" for config in configs[1:])


def test_parser_readiness_uses_result_backend(service_module, monkeypatch):
    redis_module = types.ModuleType("redis")
    redis_client = MagicMock()
    redis_client.get.return_value = "1"
    redis_module.from_url = MagicMock(return_value=redis_client)
    monkeypatch.setitem(sys.modules, "redis", redis_module)

    manager = service_module.ServiceManager({})
    manager.parser_generation = "generation"
    manager._wait_for_parser_ready()

    redis_module.from_url.assert_called_once_with(
        "redis://test:6379/1", decode_responses=True
    )


def test_parse_arguments_exposes_supported_service_flags(service_module, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["data_process_service.py", "--no-workers", "--disable-celery-flower"])
    args = service_module.parse_arguments()

    assert args.no_workers is True
    assert args.disable_celery_flower is True


def test_create_app_registers_data_process_router(service_module, monkeypatch):
    app_module = types.ModuleType("apps.data_process_app")
    app_module.router = object()
    monkeypatch.setitem(sys.modules, "apps.data_process_app", app_module)

    app = service_module.create_app()

    assert app.kwargs == {"root_path": "/api", "lifespan": service_module.lifespan}
    assert app.routers == [app_module.router]


def test_start_workers_launches_parser_with_readiness_barrier(service_module, monkeypatch):
    class FakeStdout:
        def readline(self):
            return ""

    class FakeProcess:
        pid = 123
        stdout = FakeStdout()

        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return None

    configs = [{
        "name": "parser-worker",
        "queue": "parse_q",
        "pool": "prefork",
        "concurrency": 3,
        "min_processes": 1,
        "max_tasks_per_child": 1000,
    }]
    manager = service_module.ServiceManager({"start_workers": True})
    monkeypatch.setattr(manager, "_build_worker_configs", lambda _cpus: configs)
    monkeypatch.setattr(manager, "_wait_for_parser_ready", lambda: None)
    monkeypatch.setattr(service_module.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(service_module.threading, "Thread", lambda *args, **kwargs: types.SimpleNamespace(start=lambda: None))
    service_module.service_processes["workers"].clear()

    assert manager.start_workers() is True
    assert service_module.service_processes["workers"][0]["queue"] == "parse_q"
    service_module.service_processes["workers"].clear()


def test_start_workers_cleans_up_partial_launches(service_module, monkeypatch):
    class FakeProcess:
        pid = 456
        stdout = None
        terminated = False

        def poll(self):
            return None if not self.terminated else 0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return None

        def kill(self):
            self.terminated = True

    process = FakeProcess()
    configs = [
        {"name": "parser-worker", "queue": "parse_q", "pool": "prefork", "concurrency": 3, "min_processes": 1, "max_tasks_per_child": 1000},
        {"name": "forward-worker", "queue": "forward_q", "pool": "threads", "concurrency": 2},
    ]
    manager = service_module.ServiceManager({"start_workers": True})
    monkeypatch.setattr(manager, "_build_worker_configs", lambda _cpus: configs)
    monkeypatch.setattr(manager, "_wait_for_parser_ready", lambda: None)
    popen_calls = iter([process, RuntimeError("launch failed")])

    def popen(*args, **kwargs):
        value = next(popen_calls)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(service_module.subprocess, "Popen", popen)
    monkeypatch.setattr(service_module.threading, "Thread", lambda *args, **kwargs: types.SimpleNamespace(start=lambda: None))
    service_module.service_processes["workers"].clear()

    assert manager.start_workers() is False
    assert process.terminated is True
    assert service_module.service_processes["workers"] == []


def test_parser_readiness_reports_worker_exit_and_timeout(service_module, monkeypatch):
    redis_module = types.ModuleType("redis")
    redis_client = types.SimpleNamespace(get=lambda _key: None)
    redis_module.from_url = lambda *args, **kwargs: redis_client
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    manager = service_module.ServiceManager({})
    service_module.service_processes["workers"] = [{
        "queue": "parse_q",
        "process": types.SimpleNamespace(poll=lambda: 1, returncode=9),
    }]
    monkeypatch.setattr(service_module, "DP_PARSER_STARTUP_TIMEOUT_S", 1)
    monkeypatch.setattr(service_module.time, "time", lambda: 0)
    with pytest.raises(RuntimeError, match="exited during bootstrap"):
        manager._wait_for_parser_ready()

    service_module.service_processes["workers"] = []
    times = iter([0, 2])
    monkeypatch.setattr(service_module.time, "time", lambda: next(times))
    monkeypatch.setattr(service_module.time, "sleep", lambda _seconds: None)
    with pytest.raises(TimeoutError, match="readiness timed out"):
        manager._wait_for_parser_ready()


def test_main_exits_when_service_dependencies_fail(service_module, monkeypatch):
    args = types.SimpleNamespace(
        no_workers=False,
        disable_celery_flower=False,
        redis_port=6379,
        flower_port=5555,
        api_host="0.0.0.0",
        api_port=8080,
    )
    stopped = []

    class FailedManager:
        def __init__(self, config):
            self.config = config
            self._shutdown_called = False

        def start_all_services(self):
            return False

        def stop_all_services(self):
            stopped.append(True)

    monkeypatch.setattr(service_module, "parse_arguments", lambda: args)
    monkeypatch.setattr(service_module, "ServiceManager", FailedManager)
    with pytest.raises(SystemExit):
        service_module.main()
    assert stopped == [True]
