# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Startup and admission preserve trusted ownership before any business work."""

import importlib
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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
    request = SimpleNamespace()
    assert wiring.run_options(request, 'tenant') == {}
    wiring.bind_request_reservation(request, 'user')
    wiring.associate_request(request, assistant_message_id=1)
    assert request.__dict__ == {}
    assert wiring.configure_runtime_coordination(Mock(), Mock(), Mock()) is None
    with pytest.raises(RuntimeError, match='not been initialized'):
        wiring.get_runtime_recovery()


@pytest.mark.parametrize('provider,in_cluster', [('docker', True), ('kubernetes', False)])
def test_coordinator_is_disabled_outside_trusted_kubernetes(monkeypatch, provider, in_cluster):
    monkeypatch.setattr(environment, 'NEXENT_SANDBOX_PROVIDER', provider)
    monkeypatch.setattr(environment, 'IS_DEPLOYED_BY_KUBERNETES', in_cluster)
    assert wiring.get_coordinator() is None


def test_request_binding_requires_lease_and_updates_reference(monkeypatch, configured):
    manager = Mock()
    monkeypatch.setitem(sys.modules, 'management.services.agent.lifecycle', SimpleNamespace(agent_run_manager=manager))
    monkeypatch.setitem(sys.modules, 'management.services.agent.execution', SimpleNamespace(_agent_run_identifier=lambda request: 7))
    request = SimpleNamespace()
    manager.get_distributed_lease.return_value = None
    with pytest.raises(RuntimeError, match='no admitted'):
        wiring.bind_request_reservation(request, 'user')
    with pytest.raises(RuntimeError, match='no admitted lease'):
        wiring.associate_request(request, assistant_message_id=19)
    lease = manager.get_distributed_lease.return_value = object()
    configured.reference.side_effect = ['initial', 'associated']
    wiring.bind_request_reservation(request, 'user')
    assert request._runtime_distributed_lease is lease
    assert request._runtime_run_reference == 'initial'
    wiring.associate_request(request, assistant_message_id=19)
    configured.associate.assert_called_once_with(lease, assistant_message_id=19)
    assert request._runtime_run_reference == 'associated'


@pytest.fixture
def admission(monkeypatch, configured):
    thread_module = importlib.import_module('infrastructure.concurrency')
    manager = Mock(wait_until_started=AsyncMock())
    deferred = Mock(is_bound=False)
    run_manager = Mock()
    monkeypatch.setattr(thread_module, 'runtime_thread_manager', manager)
    monkeypatch.setitem(sys.modules, 'management.services.agent.lifecycle', SimpleNamespace(agent_run_manager=run_manager))
    monkeypatch.setitem(sys.modules, 'runtime.adapters.nexent.runner', SimpleNamespace(DeferredAgentRun=lambda: deferred))
    monkeypatch.setattr(wiring, 'resolve_execution_run_id', lambda value: 'a' * 32)
    reserve = AsyncMock(return_value='token')
    monkeypatch.setattr(wiring, 'reserve_runtime_run', reserve)
    return configured, manager, deferred, run_manager, reserve


@pytest.mark.asyncio
@pytest.mark.parametrize('bound', [False, True])
async def test_automation_admission_retains_outer_holder_and_exact_release(admission, bound):
    coordinator, manager, deferred, run_manager, reserve = admission
    cancel = Mock()
    prepared = await wiring.begin_automation_admission('tenant', 'user', 7, cancel)
    reserve.call_args.kwargs['cancel']()
    deferred.cancel.assert_called_once()
    cancel.assert_called_once()
    deferred.cancel.reset_mock()
    deferred.is_bound = bound
    wiring.finish_automation_admission(prepared)
    assert deferred.cancel.call_count == int(not bound)
    coordinator.hold.assert_called_once_with(prepared.lease, 'automation')
    run_manager.release_agent_run_reservation.assert_called_once_with(7, 'user', 'token')
    coordinator.finish.assert_called_once_with(prepared.lease, holder='automation')
    manager.submit.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['start', 'reserve', 'hold'])
async def test_admission_failure_cancels_worker_and_releases_only_issued_token(admission, phase):
    coordinator, manager, deferred, run_manager, reserve = admission
    failure = RuntimeError('cannot admit')
    if phase == 'start':
        manager.wait_until_started.side_effect = failure
    elif phase == 'reserve':
        reserve.side_effect = failure
    else:
        coordinator.hold.side_effect = failure
    with pytest.raises(RuntimeError, match='cannot admit'):
        await wiring.begin_owned_agent_admission('tenant', 'user', 7, Mock(), kind='EVALUATION', holder='evaluation')
    deferred.cancel.assert_called_once()
    manager.cancel.assert_called_once()
    assert run_manager.release_agent_run_reservation.call_count == int(phase == 'hold')
    if phase == 'hold':
        run_manager.release_agent_run_reservation.assert_called_once_with(7, 'user', 'token')


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
    app = SimpleNamespace(state=SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'runtime.api.application', SimpleNamespace(app=app))
    manager = Mock()
    manager.register_service.side_effect = [SimpleNamespace(execution_id='renew'), SimpleNamespace(execution_id='recover')]
    run_manager, state = Mock(), Mock()
    return configured, api, pod, recovery, app, manager, run_manager, state


def test_startup_reconciles_owner_before_publishing_services(startup):
    coordinator, api, pod, recovery, app, manager, run_manager, state = startup
    wiring.configure_runtime_coordination(manager, run_manager, state)
    coordinator.client.ping.assert_called_once()
    recovery.recover.assert_called_once_with(startup=True)
    recovery.verify_current_owner_resources_absent.assert_called_once()
    assert coordinator.owner_facts.read('epoch')['process']['container_id'] == 'trusted'
    assert app.state.sandbox_coordinator is coordinator
    run_manager.configure_coordinator.assert_called_once_with(coordinator)
    state.configure_distributed.assert_called_once()
    assert [call.args[0] for call in manager.start_service.call_args_list] == ['renew', 'recover']
    assert wiring.get_runtime_recovery() is recovery


@pytest.mark.parametrize('failure', ['redis', 'uid', 'container_timeout'])
def test_startup_identity_failure_never_enables_admission(startup, monkeypatch, failure):
    coordinator, api, pod, recovery, app, manager, run_manager, state = startup
    if failure == 'redis':
        coordinator.client.ping.side_effect = OSError('offline')
    elif failure == 'uid':
        pod['metadata']['uid'] = 'replacement'
    else:
        pod['status']['containerStatuses'] = []
        monkeypatch.setattr(wiring.time, 'monotonic', Mock(side_effect=[0, 1, 16]))
        monkeypatch.setattr(wiring.time, 'sleep', Mock())
    with pytest.raises((OSError, RuntimeError, TimeoutError)):
        wiring.configure_runtime_coordination(manager, run_manager, state)
    run_manager.configure_coordinator.assert_not_called()
    state.configure_distributed.assert_not_called()
    manager.start_service.assert_not_called()
    recovery.recover.assert_not_called()


def test_failed_coordination_rejects_business_but_local_mode_keeps_running(monkeypatch, configured):
    from fastapi import HTTPException
    from runtime import identity
    monkeypatch.setattr(identity, 'uses_distributed_runtime', lambda: True)
    configured.lost_coordination.is_set.return_value = True
    with pytest.raises(HTTPException) as raised:
        wiring.require_business_admission()
    assert raised.value.status_code == 503
    assert raised.value.headers == {'Retry-After': '1'}
    configured.lost_coordination.is_set.return_value = False
    wiring.require_business_admission()
    monkeypatch.setattr(identity, 'uses_distributed_runtime', lambda: False)
    configured.lost_coordination.is_set.return_value = True
    wiring.require_business_admission()


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
