"""Isolated unit tests for the data-process service entrypoint."""

import importlib.util
import signal
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def service_module(monkeypatch):
    """Load the entrypoint with its runtime dependencies replaced by stubs."""
    uvicorn = types.ModuleType("uvicorn")
    uvicorn.run = MagicMock()
    ray = types.ModuleType("ray")
    ray.is_initialized = MagicMock(return_value=False)
    ray.shutdown = MagicMock()
    ray.cluster_resources = MagicMock(return_value={})
    ray.get_runtime_context = MagicMock(return_value=types.SimpleNamespace(gcs_address=""))

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
    ray_config = types.ModuleType("data_process.ray_config")
    ray_config.RayConfig = types.SimpleNamespace(init_ray_for_service=MagicMock(return_value=True))
    logging_utils = types.ModuleType("utils.logging_utils")
    logging_utils.configure_logging = MagicMock()
    constants = types.ModuleType("consts.const")
    constants.REDIS_URL = "redis://test:6379/0"
    constants.REDIS_PORT = 6379
    constants.FLOWER_PORT = 5555
    constants.RAY_DASHBOARD_PORT = 8265
    constants.RAY_DASHBOARD_HOST = "127.0.0.1"
    constants.RAY_ACTOR_NUM_CPUS = 1
    constants.RAY_NUM_CPUS = "2"
    constants.DISABLE_RAY_DASHBOARD = False
    constants.DISABLE_CELERY_FLOWER = False
    constants.DOCKER_ENVIRONMENT = False
    constants.RAY_OBJECT_STORE_MEMORY_GB = 1
    constants.RAY_preallocate_plasma = False
    constants.RAY_TEMP_DIR = "/tmp/ray"
    constants.DP_PART_PROCESSOR_COUNT = 2

    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
    monkeypatch.setitem(sys.modules, "ray", ray)
    monkeypatch.setitem(sys.modules, "dotenv", dotenv)
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)
    monkeypatch.setitem(sys.modules, "data_process.ray_config", ray_config)
    monkeypatch.setitem(sys.modules, "utils.logging_utils", logging_utils)
    monkeypatch.setitem(sys.modules, "consts.const", constants)

    module_name = "backend.data_process_service"
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path(__file__).parents[2] / "backend" / "data_process_service.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.object(signal, "signal"):
        spec.loader.exec_module(module)
    return module


def test_service_manager_merges_disable_flags(service_module, monkeypatch):
    monkeypatch.setattr(service_module, "DISABLE_RAY_DASHBOARD", True)
    monkeypatch.setattr(service_module, "DISABLE_CELERY_FLOWER", True)

    manager = service_module.ServiceManager(
        {"disable_ray_dashboard": False, "disable_celery_flower": False}
    )

    assert manager.config["disable_ray_dashboard"] is True
    assert manager.config["start_flower"] is False
    assert manager.redis_port == 6379


def test_start_ray_cluster_returns_when_disabled(service_module):
    manager = service_module.ServiceManager({"start_ray": False})

    assert manager.start_ray_cluster() is True
    service_module.RayConfig.init_ray_for_service.assert_not_called()


def test_worker_configs_isolate_forward_parent_parts_and_aggregate(service_module):
    configs = service_module.ServiceManager._build_worker_configs(4)

    assert [config["queue"] for config in configs] == [
        "process_q",
        "process_part_q",
        "forward_q",
        "forward_part_q",
        "forward_aggregate_q",
    ]
    assert configs[0]["concurrency"] == configs[1]["concurrency"] == 2
    assert configs[2]["concurrency"] == configs[3]["concurrency"] == 8
    assert configs[4]["concurrency"] == 2


def test_start_workers_launches_each_isolated_queue(service_module, monkeypatch):
    launched = []

    class _Process:
        def __init__(self, command, **kwargs):
            self.pid = len(launched) + 100
            self.stdout = types.SimpleNamespace(readline=lambda: "")
            launched.append((command, kwargs))

    monkeypatch.setattr(service_module, "RAY_NUM_CPUS", "4")
    monkeypatch.setattr(service_module, "RAY_ACTOR_NUM_CPUS", 2)
    monkeypatch.setattr(service_module.subprocess, "Popen", _Process)
    monkeypatch.setattr(service_module.threading, "Thread", lambda **kwargs: types.SimpleNamespace(start=lambda: None))

    service_module.service_processes["workers"] = []
    manager = service_module.ServiceManager({"start_workers": True})

    assert manager.start_workers() is True
    assert [row["queue"] for row in service_module.service_processes["workers"]] == [
        "process_q",
        "process_part_q",
        "forward_q",
        "forward_part_q",
        "forward_aggregate_q",
    ]
    assert len(launched) == 5
    service_module.service_processes["workers"] = []


def test_start_all_services_starts_enabled_services_in_order(service_module, monkeypatch):
    scheduler = types.SimpleNamespace(start=MagicMock())
    scheduler_module = types.ModuleType("services.auto_summary_scheduler")
    scheduler_module.auto_summary_scheduler = scheduler
    monkeypatch.setitem(sys.modules, "services.auto_summary_scheduler", scheduler_module)
    recovery = MagicMock()
    recovery_module = types.ModuleType("services.startup_recovery_service")
    recovery_module.recover_data_process_tasks = recovery
    monkeypatch.setitem(sys.modules, "services.startup_recovery_service", recovery_module)

    manager = service_module.ServiceManager(
        {"start_redis": True, "start_ray": True, "start_workers": False, "disable_celery_flower": True}
    )
    started = []
    manager.start_redis = lambda: started.append("redis") or True
    manager.start_ray_cluster = lambda: started.append("ray") or True
    manager.log_service_info = MagicMock()

    assert manager.start_all_services() is True
    assert started == ["redis", "ray"]
    recovery.assert_called_once_with()
    manager.log_service_info.assert_called_once()
    scheduler.start.assert_called_once()


def test_start_all_services_reports_failure(service_module, monkeypatch):
    scheduler_module = types.ModuleType("services.auto_summary_scheduler")
    scheduler_module.auto_summary_scheduler = types.SimpleNamespace(start=MagicMock())
    monkeypatch.setitem(sys.modules, "services.auto_summary_scheduler", scheduler_module)
    recovery = MagicMock()
    recovery_module = types.ModuleType("services.startup_recovery_service")
    recovery_module.recover_data_process_tasks = recovery
    monkeypatch.setitem(sys.modules, "services.startup_recovery_service", recovery_module)

    manager = service_module.ServiceManager(
        {"start_redis": True, "start_ray": False, "start_workers": False, "disable_celery_flower": True}
    )
    manager.start_redis = MagicMock(return_value=False)
    manager.log_service_info = MagicMock()

    assert manager.start_all_services() is False
    recovery.assert_called_once_with()
    manager.log_service_info.assert_not_called()


def test_stop_all_services_stops_workers_scheduler_and_redis(service_module, monkeypatch):
    scheduler = types.SimpleNamespace(stop=MagicMock())
    scheduler_module = types.ModuleType("services.auto_summary_scheduler")
    scheduler_module.auto_summary_scheduler = scheduler
    monkeypatch.setitem(sys.modules, "services.auto_summary_scheduler", scheduler_module)

    worker = MagicMock()
    worker.poll.return_value = None
    redis_process = MagicMock()
    service_module.service_processes.update(
        {"workers": [{"process": worker, "name": "worker", "queue": "queue"}], "redis": redis_process, "flower": None}
    )
    manager = service_module.ServiceManager({})

    manager.stop_all_services()

    worker.terminate.assert_called_once()
    worker.wait.assert_called_once_with(timeout=10)
    redis_process.terminate.assert_called_once()
    redis_process.wait.assert_called_once_with(timeout=5)
    scheduler.stop.assert_called_once()
    assert service_module.service_processes["workers"] == []
    assert service_module.service_processes["redis"] is None
    manager.stop_all_services()
    assert scheduler.stop.call_count == 1


def test_create_app_registers_data_process_router(service_module, monkeypatch):
    app_module = types.ModuleType("apps.data_process_app")
    app_module.router = object()
    monkeypatch.setitem(sys.modules, "apps.data_process_app", app_module)

    app = service_module.create_app()

    assert app.kwargs == {"root_path": "/api", "lifespan": service_module.lifespan}
    assert app.routers == [app_module.router]


def test_check_redis_connection_handles_success_import_error_and_runtime_error(service_module, monkeypatch):
    manager = service_module.ServiceManager({})
    redis_client = MagicMock()
    redis_module = types.ModuleType("redis")
    redis_module.from_url = MagicMock(return_value=redis_client)
    redis_service = types.ModuleType("services.redis_service")
    redis_service.get_redis_service = MagicMock(return_value=types.SimpleNamespace(cleanup_error_info_keys=lambda: {"removed": 1}))
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "services.redis_service", redis_service)

    assert manager._check_redis_connection("redis://ignored") is True
    redis_client.ping.assert_called_once()

    monkeypatch.delitem(sys.modules, "redis")
    assert manager._check_redis_connection("redis://ignored") is False

    redis_module.from_url.side_effect = RuntimeError("unreachable")
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    assert manager._check_redis_connection("redis://ignored") is False


def test_start_ray_cluster_tracks_new_cluster_and_ray_address(service_module, monkeypatch):
    manager = service_module.ServiceManager({"start_ray": True})
    service_module.ray.is_initialized.return_value = False
    service_module.ray.get_runtime_context.return_value = types.SimpleNamespace(gcs_address="ray://cluster")

    assert manager.start_ray_cluster() is True

    service_module.RayConfig.init_ray_for_service.assert_called_once_with(
        num_cpus=2,
        dashboard_port=8265,
        try_connect_first=True,
        include_dashboard=True,
    )
    assert manager._ray_cluster_started is True
    assert manager.config["ray_address"] == "ray://cluster"
    assert service_module.service_processes["ray_cluster"] is True
    monkeypatch.delenv("RAY_ADDRESS", raising=False)


def test_start_ray_cluster_uses_direct_fallback_when_helper_fails(service_module):
    manager = service_module.ServiceManager({"start_ray": True, "disable_ray_dashboard": True})
    service_module.RayConfig.init_ray_for_service.return_value = False
    service_module.ray.is_initialized.return_value = False
    service_module.ray.init = MagicMock()

    assert manager.start_ray_cluster() is True

    service_module.ray.init.assert_called_once()
    assert manager._ray_cluster_started is True


def test_parse_arguments_and_lifespan_shutdown(service_module, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "data_process_service.py",
        "--no-workers",
        "--no-ray",
        "--disable-celery-flower",
        "--disable-ray-dashboard",
        "--redis-port", "6380",
        "--api-port", "5013",
    ])
    args = service_module.parse_arguments()
    assert args.no_workers is True
    assert args.no_ray is True
    assert args.redis_port == 6380
    assert args.api_port == 5013

    manager = MagicMock()
    manager._shutdown_called = False
    service_module.service_manager = manager
    lifecycle = service_module.lifespan(object())

    import asyncio

    async def run_lifespan():
        async with lifecycle:
            pass

    asyncio.run(run_lifespan())
    manager.stop_all_services.assert_called_once()


def test_stop_all_services_kills_timed_out_worker_and_stops_ray(service_module, monkeypatch):
    scheduler_module = types.ModuleType("services.auto_summary_scheduler")
    scheduler_module.auto_summary_scheduler = types.SimpleNamespace(stop=MagicMock())
    monkeypatch.setitem(sys.modules, "services.auto_summary_scheduler", scheduler_module)
    worker = MagicMock()
    worker.poll.return_value = None
    worker.wait.side_effect = [service_module.subprocess.TimeoutExpired("worker", 10), None]
    service_module.ray.is_initialized.return_value = True
    service_module.service_processes.update({"workers": [{"process": worker, "name": "worker", "queue": "queue"}], "redis": None, "flower": None})
    manager = service_module.ServiceManager({})
    manager._ray_cluster_started = True
    monkeypatch.setattr(service_module.time, "sleep", lambda seconds: None)

    manager.stop_all_services()

    worker.kill.assert_called_once()
    service_module.ray.shutdown.assert_called_once()
    assert manager._ray_cluster_started is False
