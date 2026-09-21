"""Native system endpoints and cancellation ownership regressions."""

import logging
import sys
from concurrent.futures import CancelledError
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from nexent.core.agents import sandbox as sb


@pytest.fixture
def system(monkeypatch):
    pool = sb.SandboxPoolManager()
    config = sb.SandboxConfig(level=sb.SandboxLevel.DOCKER, scope=sb.SandboxScope.SYSTEM)
    container = MagicMock()
    container.attrs = {"NetworkSettings": {
        "Networks": {"bridge": {}},
        "Ports": {"8888/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49173"}]},
    }}
    container.labels = {"com.nexent.sandbox": "runtime"}
    container.name = sb.SANDBOX_CONTAINER_NAME
    container.status = "running"
    run = MagicMock(return_value=container)
    client = SimpleNamespace(
        version=lambda: {"Version": "20.10.24"},
        containers=SimpleNamespace(run=run, list=lambda **kwargs: [container]),
    )
    get = MagicMock(return_value=SimpleNamespace(raise_for_status=lambda: None, json=list))
    monkeypatch.setitem(sys.modules, "docker", SimpleNamespace(from_env=lambda: client))
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=get))
    monkeypatch.setattr(sb, "_is_containerized_runtime", lambda: False)
    monkeypatch.setattr(sb, "_seed_pnpm_offline_store", lambda container: None)
    return SimpleNamespace(
        pool=pool, config=config, container=container, run=run, get=get,
        logger=logging.getLogger(__name__), scope=sb.RunCancellationScope(),
    )


def test_native_system_uses_actual_dynamic_port(system):
    s = system
    owner = s.pool._build_system_docker_executor(s.config, s.logger, {"network": sb.SANDBOX_NETWORK_NAME})
    assert s.run.call_args.kwargs["network"] == "bridge"
    assert s.run.call_args.kwargs["ports"] == {"8888/tcp": ("127.0.0.1", None)}
    assert owner.base_url == "http://127.0.0.1:49173"
    assert owner.port == 49173
    s.get.assert_called_once_with("http://127.0.0.1:49173/api/kernels", timeout=1)


def test_recovery_reads_dynamic_mapping_on_bridge(system):
    s = system
    owner = s.pool._recover_docker_container(s.config, s.logger, False)
    assert owner.base_url == "http://127.0.0.1:49173"
    s.run.assert_not_called()


@pytest.mark.parametrize("bindings", [[], [{"HostIp": "0.0.0.0", "HostPort": "49173"}]])
def test_missing_or_public_mapping_fails_without_probing_other_service(system, bindings):
    s = system
    s.container.attrs["NetworkSettings"]["Ports"]["8888/tcp"] = bindings
    with pytest.raises(RuntimeError, match="no effective loopback"):
        s.pool._build_system_docker_executor(s.config, s.logger, {})
    s.get.assert_not_called()
    s.container.remove.assert_called_once_with(force=True)


@pytest.mark.parametrize("phase", ["before_create", "after_create", "probe", "shutdown"])
def test_cancel_unpublished_startup_cleans_only_created_container(system, phase):
    s = system
    if phase == "before_create":
        s.scope.cancel()
    elif phase == "after_create":
        def create(*args, **kwargs):
            s.scope.cancel()
            return s.container
        s.run.side_effect = create
    else:
        def probe(*args, **kwargs):
            if phase == "shutdown":
                s.pool._stop_evict.set()
            else:
                s.scope.cancel()
            raise OSError("connection closed")
        s.get.side_effect = probe
    with pytest.raises(CancelledError):
        s.pool._build_system_docker_executor(s.config, s.logger, {}, s.scope)
    if phase == "before_create":
        s.run.assert_not_called()
        s.container.remove.assert_not_called()
    else:
        s.container.remove.assert_called_once_with(force=True)
    assert not s.pool._system_containers


def test_cancel_after_kernel_creation_preserves_shared_owner_and_b(system, monkeypatch):
    s = system
    owner = SimpleNamespace(container=s.container, base_url="http://127.0.0.1:49173")
    s.pool._system_containers[s.config.docker_image] = owner
    b = MagicMock(container=s.container)
    s.pool._executors[id(b)] = b
    s.pool._lease_owners[id(b)] = owner
    lease = MagicMock(container=s.container)
    def create_lease(*args, **kwargs):
        s.scope.cancel()
        return lease
    monkeypatch.setattr(s.pool, "_is_alive", lambda owner: True)
    monkeypatch.setattr(sb, "_DockerKernelLease", create_lease)
    with pytest.raises(CancelledError):
        s.pool._acquire_shared_docker_kernel(s.config, s.logger, False, s.scope)
    lease.cleanup.assert_called_once()
    b.cleanup.assert_not_called()
    s.container.remove.assert_not_called()
    assert s.pool._system_containers[s.config.docker_image] is owner


def test_immediate_release_of_a_preserves_b_and_shared_container(system, monkeypatch):
    s = system
    owner = MagicMock()
    a, b = MagicMock(), MagicMock()
    s.pool._system_containers[s.config.docker_image] = owner
    for lease in (a, b):
        s.pool._lease_owners[id(lease)] = owner
        s.pool._executors[id(lease)] = lease
        s.pool._in_use[id(lease)] = s.config.docker_image
    destroy = MagicMock()
    monkeypatch.setattr(s.pool, "_destroy_executor", destroy)
    s.pool.release_immediate(a, s.logger)
    destroy.assert_called_once_with(a, s.logger)
    assert s.pool._system_containers[s.config.docker_image] is owner
    assert s.pool._executors[id(b)] is b


def test_unrelated_same_name_container_is_not_removed(system):
    s = system
    s.container.labels = {}
    s.pool._remove_stale_docker_containers(s.config, s.logger)
    s.container.remove.assert_not_called()


def test_cancel_before_owner_publication_cleans_unpublished_owner(system, monkeypatch):
    s = system
    owner = SimpleNamespace(container=s.container, base_url="http://127.0.0.1:49173")
    monkeypatch.setattr(s.pool, "_recover_docker_container", lambda *args: None)
    monkeypatch.setattr(s.pool, "_remove_stale_docker_containers", lambda *args: None)
    def build(*args, cancellation_scope=None):
        assert cancellation_scope is s.scope
        s.scope.cancel()
        return owner
    monkeypatch.setattr(s.pool, "_build_executor", build)
    destroy = MagicMock()
    monkeypatch.setattr(s.pool, "_destroy_executor", destroy)
    with pytest.raises(CancelledError):
        s.pool._acquire_shared_docker_kernel(s.config, s.logger, False, s.scope)
    destroy.assert_called_once_with(owner, s.logger)
    assert not s.pool._system_containers
    assert s.pool._container_build_lock.acquire(blocking=False)
    s.pool._container_build_lock.release()


def test_system_cancellation_never_falls_back_to_local(system, monkeypatch):
    s = system
    monkeypatch.setitem(sys.modules, "smolagents.remote_executors", SimpleNamespace(DockerExecutor=object()))
    builder = MagicMock(side_effect=CancelledError("cancelled"))
    local = MagicMock()
    monkeypatch.setattr(s.pool, "_build_system_docker_executor", builder)
    monkeypatch.setattr(sb, "_make_local_executor", local)
    with pytest.raises(CancelledError):
        s.pool._build_docker_executor(s.config, s.logger, cancellation_scope=s.scope)
    assert builder.call_args.kwargs["cancellation_scope"] is s.scope
    local.assert_not_called()
