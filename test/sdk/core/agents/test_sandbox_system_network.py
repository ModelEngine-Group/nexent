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
    container.labels = {"com.nexent.sandbox": "runtime", sb.TLS_LABEL: sb.TLS_VERSION}
    container.name = sb.SANDBOX_CONTAINER_NAME
    container.status = "running"
    run = MagicMock(return_value=container)
    client = SimpleNamespace(
        version=lambda: {"Version": "20.10.24"},
        containers=SimpleNamespace(run=run, list=lambda **kwargs: [container]),
    )
    get = MagicMock(return_value=SimpleNamespace(raise_for_status=lambda: None, json=list))
    tls = SimpleNamespace(http=SimpleNamespace(get=get), ssl_context=object(), close=MagicMock())
    monkeypatch.setattr(sb, 'load_container_tls', lambda *args, **kwargs: tls)
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
    assert owner.base_url == "https://127.0.0.1:49173"
    assert owner.port == 49173
    s.get.assert_called_once_with("https://127.0.0.1:49173/api/kernels", timeout=1)


def test_recovery_reads_dynamic_mapping_on_bridge(system):
    s = system
    owner = s.pool._recover_docker_container(s.config, s.logger, False)
    assert owner.base_url == "https://127.0.0.1:49173"
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


@pytest.mark.parametrize('port', ['', None, 'bad', '0', '-1', '65536'])
def test_invalid_published_ports_are_not_used(system, port):
    system.container.attrs['NetworkSettings']['Ports']['8888/tcp'] = [
        {'HostIp': '127.0.0.1', 'HostPort': port},
    ]
    with pytest.raises(RuntimeError, match='no effective loopback'):
        sb._published_sandbox_port(system.container)
    assert system.pool._recover_docker_container(system.config, system.logger, False) is None
    system.get.assert_not_called()


def test_port_parser_skips_invalid_binding_and_uses_valid_loopback(system):
    system.container.attrs['NetworkSettings']['Ports']['8888/tcp'] = [
        {'HostIp': '0.0.0.0', 'HostPort': '8888'},
        {'HostIp': '127.0.0.1', 'HostPort': 'bad'},
        {'HostIp': '127.0.0.1', 'HostPort': '65535'},
    ]
    assert sb._published_sandbox_port(system.container) == 65535


@pytest.mark.parametrize('matching_mount', [False, True])
def test_recovery_requires_matching_bind_mount(system, tmp_path, matching_mount):
    system.config.workspace_mode = 'bind'
    system.config.container_workspace_root = '/mnt/work'
    system.config.extra_kwargs = {'workspace_root': str(tmp_path)}
    mapping = system.config.bind_workspace()
    system.container.labels['com.nexent.workspace'] = mapping.mount_id
    system.container.attrs['Mounts'] = [{
        'Type': 'bind', 'Source': str(tmp_path if matching_mount else tmp_path / 'wrong'),
        'Destination': '/mnt/work', 'RW': True,
    }]
    result = system.pool._recover_docker_container(system.config, system.logger, False)
    if matching_mount:
        assert result.container is system.container
        system.get.assert_called_once()
    else:
        assert result is None
        system.get.assert_not_called()
    system.container.remove.assert_not_called()


@pytest.mark.parametrize('response', ['invalid', 'exception'])
def test_system_startup_timeout_cleans_created_container(system, monkeypatch, response):
    times = iter([0, 0, 1000])
    monkeypatch.setattr(sb.time, 'monotonic', lambda: next(times))
    monkeypatch.setattr(system.pool._stop_evict, 'wait', lambda _: None)
    if response == 'invalid':
        system.get.return_value = SimpleNamespace(raise_for_status=lambda: None, json=dict)
    else:
        system.get.side_effect = OSError('unavailable')
    with pytest.raises(RuntimeError, match='did not become ready'):
        system.pool._build_system_docker_executor(system.config, system.logger, {})
    system.container.remove.assert_called_once_with(force=True)
    assert not system.pool._system_containers


def test_changed_system_workspace_does_not_destroy_active_owner(system, tmp_path, monkeypatch):
    original = sb.SandboxConfig(
        level=sb.SandboxLevel.DOCKER, workspace_mode='bind', container_workspace_root='/mnt/old',
        extra_kwargs={'workspace_root': str(tmp_path)},
    )
    owner = SimpleNamespace(_nexent_sandbox_config=original, container=system.container)
    system.pool._system_containers[system.config.docker_image] = owner
    destroy = MagicMock()
    monkeypatch.setattr(system.pool, '_destroy_executor', destroy)
    with pytest.raises(RuntimeError, match='workspace changed'):
        system.pool._acquire_shared_docker_kernel(system.config, system.logger, False)
    destroy.assert_not_called()
    assert system.pool._system_containers[system.config.docker_image] is owner


def test_failed_new_lease_preserves_owner_with_active_leases(system, monkeypatch):
    owner = SimpleNamespace(_nexent_sandbox_config=system.config, container=system.container, base_url='http://127.0.0.1')
    system.pool._system_containers[system.config.docker_image] = owner
    active = SimpleNamespace(container=system.container)
    system.pool._executors[id(active)] = active
    monkeypatch.setattr(system.pool, '_is_alive', lambda _: True)
    monkeypatch.setattr(sb, '_DockerKernelLease', MagicMock(side_effect=OSError('connect failed')))
    destroy = MagicMock()
    monkeypatch.setattr(system.pool, '_destroy_executor', destroy)
    with pytest.raises(RuntimeError, match='preserving the shared container'):
        system.pool._acquire_shared_docker_kernel(system.config, system.logger, False)
    destroy.assert_not_called()
    assert system.pool._executors[id(active)] is active


def test_cancel_before_lease_registration_preserves_shared_owner(system, monkeypatch):
    owner = SimpleNamespace(_nexent_sandbox_config=system.config, container=system.container, base_url='http://127.0.0.1')
    system.pool._system_containers[system.config.docker_image] = owner
    lease = MagicMock()
    monkeypatch.setattr(system.pool, '_is_alive', lambda _: True)
    monkeypatch.setattr(sb, '_DockerKernelLease', lambda *args, **kwargs: lease)
    def wrap(executor, *args):
        system.scope.cancel()
        return executor
    monkeypatch.setattr(sb, '_wrap_executor', wrap)
    with pytest.raises(CancelledError, match='acquisition cancelled'):
        system.pool._acquire_shared_docker_kernel(system.config, system.logger, False, system.scope)
    lease.cleanup.assert_called_once()
    assert not system.pool._executors
    assert system.pool._system_containers[system.config.docker_image] is owner
