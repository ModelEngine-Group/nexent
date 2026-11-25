# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Startup and admission preserve trusted ownership before any business work."""

import asyncio
import importlib
import sys
from concurrent.futures import Future
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from fastapi import HTTPException

from contracts.constants import environment
from runtime import sandbox_runtime as wiring
from runtime import sandbox_services as services
from runtime.sandbox_coordination import SandboxRunBusy
from runtime.sandbox_journal import SandboxCoordinationUnknown, SandboxRunJournal

from nexent.core.agents.sandbox_contracts import SandboxOwner, SystemSandboxProfile


@pytest.fixture
def owner():
    return SandboxOwner('release', 'ns', 'runtime', 'uid', '10.0.0.1', 'epoch')


@pytest.fixture
def configured(monkeypatch, owner, tmp_path):
    coordinator = Mock(owner=owner, journal=SandboxRunJournal(tmp_path / 'control'))
    monkeypatch.setattr(wiring, 'get_coordinator', lambda: coordinator)
    return coordinator


@pytest.mark.asyncio
async def test_non_kubernetes_requests_keep_existing_local_contract(monkeypatch):
    monkeypatch.setattr(wiring, "get_coordinator", lambda: None)
    assert await wiring.reserve_agentos_sandbox("t", "u", 7, "a" * 32, kind="CHAT", cancel=Mock()) is None
    assert wiring.configure_runtime_coordination(Mock(), Mock()) is None


@pytest.mark.parametrize('provider,in_cluster', [('docker', True), ('kubernetes', False)])
def test_coordinator_is_disabled_outside_trusted_kubernetes(monkeypatch, provider, in_cluster):
    monkeypatch.setattr(environment, 'NEXENT_SANDBOX_PROVIDER', provider)
    monkeypatch.setattr(environment, 'IS_DEPLOYED_BY_KUBERNETES', in_cluster)
    assert wiring.get_coordinator() is None


@pytest.fixture
def managed_io(monkeypatch):
    async def run(_name, func, *args, lane, owner):
        assert (lane, owner) == ("control-io", "runtime")
        return func(*args)

    monkeypatch.setattr(wiring, "run_blocking", run)


@pytest.mark.asyncio
async def test_agentos_sandbox_activation_and_worker_exit_control_lease(configured, managed_io):
    cancel = Mock()
    owned = await wiring.reserve_agentos_sandbox("t", "u", 7, "a" * 32, kind="CHAT", cancel=cancel)
    configured.reserve.assert_called_once_with("t", "u", 7, "a" * 32, kind="CHAT", cancel=cancel)
    configured.activate.assert_called_once_with(owned.lease)
    worker = Future()
    await wiring.release_agentos_sandbox(owned, worker)
    configured.finish.assert_not_called()
    worker.set_result(None)
    configured.finish.assert_called_once_with(owned.lease)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase, code", [("busy", 409), ("lost", 503)])
async def test_agentos_admission_failure_only_releases_acquired_lease(configured, managed_io, phase, code):
    if phase == "busy":
        configured.reserve.side_effect = SandboxRunBusy()
    else:
        configured.activate.side_effect = SandboxCoordinationUnknown()
    with pytest.raises(HTTPException) as raised:
        await wiring.reserve_agentos_sandbox("t", "u", 7, "a" * 32, kind="CHAT", cancel=Mock())
    assert raised.value.status_code == code
    assert configured.finish.call_count == int(phase == "lost")


@pytest.mark.asyncio
async def test_cancelled_agentos_admission_releases_late_exact_lease(monkeypatch, configured):
    started, unblock = asyncio.Event(), asyncio.Event()

    async def run(name, func, *, lane, owner):
        if name == "agentos-sandbox-reserve":
            started.set()
            await unblock.wait()
        return func()

    monkeypatch.setattr(wiring, "run_blocking", run)
    task = asyncio.create_task(wiring.reserve_agentos_sandbox("t", "u", 7, "a" * 32, kind="CHAT", cancel=Mock()))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    configured.finish.assert_not_called()
    unblock.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    configured.finish.assert_called_once_with(configured.reserve.return_value)


@pytest.fixture
def startup(monkeypatch, configured):
    api = Mock()
    pod = {'metadata': {'uid': 'uid'}, 'status': {'containerStatuses': [{
        'name': 'nexent-runtime', 'containerID': 'containerd://trusted', 'state': {'running': {}}}]}}
    api.read_namespaced_pod.return_value = pod
    monkeypatch.setattr(services, 'kubernetes_api', lambda: nullcontext(api))
    monkeypatch.setattr(environment, 'NEXENT_RUNTIME_CONTAINER_NAME', 'nexent-runtime')
    monkeypatch.setattr(wiring, 'process_identity', lambda *args: {
        'pid': 123, 'start_ticks': '100', 'boot_id': 'boot', 'container_id': 'trusted', 'container_name': 'nexent-runtime'})
    recovery = Mock()
    recovery.recover.return_value = {'restart_confirmed': True}
    recovery_module = importlib.import_module('runtime.sandbox_recovery')
    monkeypatch.setattr(recovery_module, 'SandboxRuntimeRecovery', Mock(return_value=recovery))
    app = SimpleNamespace(state=SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'runtime.api.application', SimpleNamespace(app=app))
    manager = Mock()
    manager.register_service.side_effect = [SimpleNamespace(execution_id='renew'), SimpleNamespace(execution_id='recover')]
    return configured, api, pod, recovery, app, manager


def test_startup_reconciles_owner_before_publishing_services(startup):
    coordinator, api, pod, recovery, app, manager = startup
    wiring.configure_runtime_coordination(manager, app.state)
    coordinator.client.ping.assert_called_once()
    assert recovery.recover.call_args_list == [call(startup=True), call()]
    recovery.verify_current_owner_resources_absent.assert_called_once()
    assert coordinator.owner_facts.read('epoch')['process']['container_id'] == 'trusted'
    assert app.state.sandbox_coordinator is coordinator
    assert app.state.sandbox_restart_cutoff is not None
    assert [call.args[0] for call in manager.start_service.call_args_list] == ['renew', 'recover']


@pytest.mark.parametrize('failure', ['redis', 'uid', 'container_timeout'])
def test_startup_identity_failure_never_enables_admission(startup, monkeypatch, failure):
    coordinator, api, pod, recovery, app, manager = startup
    if failure == 'redis':
        coordinator.client.ping.side_effect = OSError('offline')
    elif failure == 'uid':
        pod['metadata']['uid'] = 'replacement'
    else:
        pod['status']['containerStatuses'] = []
        monkeypatch.setattr(wiring.time, 'monotonic', Mock(side_effect=[0, 1, 16]))
        monkeypatch.setattr(wiring.time, 'sleep', Mock())
    with pytest.raises((OSError, RuntimeError, TimeoutError)):
        wiring.configure_runtime_coordination(manager, app.state)
    assert not hasattr(app.state, "sandbox_coordinator")
    manager.start_service.assert_not_called()
    recovery.recover.assert_not_called()


def test_failed_coordination_rejects_business_but_local_mode_keeps_running(monkeypatch, configured):
    configured.lost_coordination.is_set.return_value = True
    with pytest.raises(HTTPException) as raised:
        wiring.check_agentos_admission()
    assert raised.value.status_code == 503
    configured.lost_coordination.is_set.return_value = False
    wiring.check_agentos_admission()
    monkeypatch.setattr(wiring, "get_coordinator", lambda: None)
    wiring.check_agentos_admission()


def test_service_binding_checks_mount_and_keeps_ipv6_callback_address(monkeypatch, configured, owner):
    profile = SystemSandboxProfile('image:tag', 'claim')
    workspace = Mock(owner_root='/mnt/owned')
    monkeypatch.setattr(services, 'KubernetesWorkspace', Mock(return_value=workspace))
    backend_type = Mock()
    monkeypatch.setattr(services, 'KubernetesSandboxBackend', backend_type)
    cached_services = services.get_sandbox_services
    cached_services.cache_clear()
    try:
        workspace_result, backend, callbacks = services.get_sandbox_services(owner, profile, '/work', '/mount', True)
        assert workspace_result is workspace and configured.sandbox_backend is backend
        verify = backend_type.call_args.kwargs['verify_workspace']
        for gid, mode, allowed in [(1000, 0o2770, True), (999, 0o2770, False), (1000, 0o0770, False)]:
            monkeypatch.setattr(services, 'Path', lambda value: SimpleNamespace(stat=lambda: SimpleNamespace(st_gid=gid, st_mode=mode)))
            if allowed:
                verify()
            else:
                with pytest.raises(RuntimeError, match='setgid'):
                    verify()
        monkeypatch.setattr(services, 'get_sandbox_services', lambda *args: (workspace, backend, callbacks))
        config = SimpleNamespace(owner=SimpleNamespace(pod_ip='fd00::1'), system_profile=profile, extra_kwargs={})
        services.bind_runtime_sandbox(config, execution_run_id='a' * 32)
        assert config.runtime_backend is backend and config.callback_registry is callbacks
        assert config.workspace_access is workspace
        assert config.run_lifecycle is configured.lifecycle.return_value
        assert config.callback_endpoint == 'http://[fd00::1]:5014/internal/sandbox/tool-invoke'
        assert config.extra_kwargs['workspace_root'] == '/mnt/owned'
    finally:
        cached_services.cache_clear()


def test_service_binding_requires_initialized_facts(monkeypatch, configured, owner):
    configured.owner_facts = None
    services.get_sandbox_services.cache_clear()
    with pytest.raises(RuntimeError, match='initialized'):
        services.get_sandbox_services(owner, SystemSandboxProfile('image:tag', 'claim'), '/work', '/mount')


def test_kubernetes_client_uses_only_incluster_configuration(monkeypatch):
    from kubernetes import client, config
    configuration, transport, api = object(), object(), object()
    load = Mock()
    monkeypatch.setattr(config, 'load_incluster_config', load)
    monkeypatch.setattr(client, 'Configuration', Mock(return_value=configuration))
    session = Mock()
    session.__enter__ = Mock(return_value=transport)
    session.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(client, 'ApiClient', Mock(return_value=session))
    construct = Mock(return_value=api)
    monkeypatch.setattr(client, 'CoreV1Api', construct)
    with services.kubernetes_api() as actual:
        assert actual is api
    load.assert_called_once_with(client_configuration=configuration)
    construct.assert_called_once_with(transport)
    session.__exit__.assert_called_once()


@pytest.mark.parametrize('options,enabled', [({'provider': 'docker'}, False),
    ({'provider': 'kubernetes', 'enabled': False}, False),
    ({'provider': 'kubernetes', 'owner': 'owner', 'system_profile': 'profile'}, True)])
def test_callback_registry_is_available_only_for_enabled_kubernetes(monkeypatch, options, enabled):
    from runtime.adapters.nexent import sandbox
    registry = object()
    get_services = Mock(return_value=(object(), object(), registry))
    monkeypatch.setattr(services, 'get_sandbox_services', get_services)
    monkeypatch.setattr(sandbox, 'get_runtime_sandbox_options', lambda: options)
    assert services.current_callback_registry() is (registry if enabled else None)
    assert get_services.call_count == int(enabled)
