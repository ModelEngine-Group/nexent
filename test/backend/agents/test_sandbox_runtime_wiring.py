# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Startup and admission preserve trusted ownership before any business work."""

import importlib
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.constants import environment
from runtime import sandbox_runtime as wiring
from runtime import sandbox_services as services
from runtime.sandbox_journal import SandboxRunJournal

from nexent.core.agents.sandbox_contracts import SandboxOwner, SystemSandboxProfile


@pytest.fixture
def owner():
    return SandboxOwner('release', 'ns', 'runtime', 'uid', '10.0.0.1', 'epoch')


@pytest.fixture
def configured(monkeypatch, owner, tmp_path):
    coordinator = Mock(owner=owner, journal=SandboxRunJournal(tmp_path / 'control'))
    monkeypatch.setattr(wiring, 'get_coordinator', lambda: coordinator)
    return coordinator


def test_non_kubernetes_requests_keep_existing_local_contract(monkeypatch):
    monkeypatch.setattr(wiring, 'get_coordinator', lambda: None)
    assert wiring.initialize_sandbox_coordination(Mock()) is None


@pytest.mark.parametrize('provider,in_cluster', [('docker', True), ('kubernetes', False)])
def test_coordinator_is_disabled_outside_trusted_kubernetes(monkeypatch, provider, in_cluster):
    monkeypatch.setattr(environment, 'NEXENT_SANDBOX_PROVIDER', provider)
    monkeypatch.setattr(environment, 'IS_DEPLOYED_BY_KUBERNETES', in_cluster)
    assert wiring.get_coordinator() is None


def test_prepared_workspace_binds_exact_owner_and_releases_lease(monkeypatch, configured, tmp_path):
    config = SimpleNamespace()
    actor = SimpleNamespace(tenant_id="tenant", user_id="owner")
    workspace = Mock(owner_root=tmp_path)
    run_dir = tmp_path / ("a" * 32)
    workspace.run_path.return_value = run_dir
    bind = Mock(side_effect=lambda config, **kwargs: setattr(config, "workspace_access", workspace))
    monkeypatch.setattr(services, "bind_runtime_sandbox", bind)
    event = Mock()

    path, root, release = services.prepare_sandbox_workspace(config, actor, 7, "a" * 32, event)
    lease = configured.reserve.return_value
    assert (path, root) == (str(run_dir), str(tmp_path))
    configured.reserve.assert_called_once_with("tenant", "owner", 7, "a" * 32, cancel=event.set)
    configured.activate.assert_called_once_with(lease)
    configured.record_workspace.assert_called_once_with("a" * 32, run_dir)
    workspace.prepare_run.assert_called_once_with("tenant", "owner", "a" * 32)
    configured.finish.assert_not_called()
    release()
    configured.finish.assert_called_once_with(lease)


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
    recovery_module = importlib.import_module('runtime.sandbox_recovery')
    monkeypatch.setattr(recovery_module, 'SandboxRuntimeRecovery', Mock(return_value=recovery))
    monkeypatch.setattr(environment, 'NEXENT_SANDBOX_ENABLED', True)
    manager = Mock()
    manager.register_service.side_effect = [SimpleNamespace(execution_id='renew'), SimpleNamespace(execution_id='recover')]
    return configured, api, pod, recovery, manager


def test_startup_reconciles_owner_before_publishing_services(startup):
    coordinator, _api, _pod, recovery, manager = startup
    assert wiring.initialize_sandbox_coordination(manager) is coordinator
    coordinator.client.ping.assert_called_once()
    recovery.recover.assert_called_once_with(startup=True)
    recovery.verify_current_owner_resources_absent.assert_called_once()
    assert coordinator.owner_facts.read('epoch')['process']['container_id'] == 'trusted'
    assert [call.args[0] for call in manager.start_service.call_args_list] == ['renew', 'recover']


@pytest.mark.parametrize('failure', ['redis', 'uid', 'container_timeout'])
def test_startup_identity_failure_never_enables_admission(startup, monkeypatch, failure):
    coordinator, api, pod, recovery, manager = startup
    if failure == 'redis':
        coordinator.client.ping.side_effect = OSError('offline')
    elif failure == 'uid':
        pod['metadata']['uid'] = 'replacement'
    else:
        pod['status']['containerStatuses'] = []
        monkeypatch.setattr(wiring.time, 'monotonic', Mock(side_effect=[0, 1, 16]))
        monkeypatch.setattr(wiring.time, 'sleep', Mock())
    with pytest.raises((OSError, RuntimeError, TimeoutError)):
        wiring.initialize_sandbox_coordination(manager)
    manager.start_service.assert_not_called()
    recovery.recover.assert_not_called()


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
