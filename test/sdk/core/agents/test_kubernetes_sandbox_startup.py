# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from copy import deepcopy
from unittest.mock import Mock

import pytest

from nexent.core.agents.sandbox_contracts import SandboxGenerationChangedError, SandboxOwner, SystemSandboxProfile
from nexent.core.agents.sandbox_kubernetes import KubernetesSandboxBackend


@pytest.fixture
def startup(mocker):
    api = Mock()
    owner = SandboxOwner('release', 'namespace', 'runtime-a', 'runtime-uid', '10.0.0.1', 'epoch-a')
    profile = SystemSandboxProfile('sandbox:image', 'claim')
    backend = KubernetesSandboxBackend(lambda: nullcontext(api), workspace_subpath='workdir/owners/runtime-uid')
    pod, service = backend.manifests(owner, profile)
    pod['metadata'] = deepcopy(pod['metadata'])
    service['metadata'] = deepcopy(service['metadata'])
    pod['metadata']['uid'] = 'sandbox-uid'
    service['metadata']['uid'] = 'service-uid'
    pod['status'] = {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}],
                     'containerStatuses': [{'name': 'sandbox', 'containerID': 'container-a', 'restartCount': 0,
                                            'state': {'running': {'startedAt': 'time'}}}]}
    runtime = {'metadata': {'uid': owner.pod_uid}, 'spec': {'nodeName': 'node-a'}, 'status': {'podIP': owner.pod_ip}}
    api.read_namespaced_pod.side_effect = lambda name, *a, **k: runtime if name == owner.pod_name else pod
    api.read_namespaced_persistent_volume_claim.return_value = {'spec': {'accessModes': ['ReadWriteMany']},
                                                               'status': {'phase': 'Bound'}}
    api.create_namespaced_pod.return_value = pod
    api.create_namespaced_service.return_value = service
    process = mocker.patch('nexent.core.agents.sandbox_kubernetes_exec.KubernetesProcessAdapter').return_value
    process.run.return_value = Mock(stdout=b'PUBLIC CERTIFICATE', exit_code=0)
    tls = mocker.patch('nexent.core.agents.sandbox_kubernetes.SandboxTLSClient').return_value
    tls.http.get.return_value.status_code = 200
    tls.http.get.return_value.json.return_value = []
    return backend, owner, profile, api, runtime, pod, process, tls


def test_startup_pins_trusted_certificate_and_reuses_owner_without_new_resources(startup):
    backend, owner, profile, api, _, pod, process, tls = startup
    connection = backend.ensure_system(owner, profile)
    assert backend.ensure_system(owner, profile) is connection
    assert connection.generation == 'sandbox-uid:container-a:0'
    assert connection.base_url.endswith('.namespace.svc:8080')
    assert api.create_namespaced_pod.call_count == api.create_namespaced_service.call_count == 1
    process.run.assert_called_once()
    assert process.run.call_args.args[0] == ['cat', '/home/sandbox/.nexent-jupyter-tls/server.crt']
    assert tls.http.get.call_args.args[0] == connection.base_url + '/api/kernels'


def test_service_endpoint_publication_lag_retries_only_safe_readiness(startup):
    from requests.exceptions import ConnectionError

    backend, owner, profile, api, _, _, process, tls = startup
    ready = tls.http.get.return_value
    tls.http.get.side_effect = [ConnectionError('Service endpoint not published yet'), ready]
    assert backend.ensure_system(owner, profile).pod_uid == 'sandbox-uid'
    assert tls.http.get.call_count == 2
    assert api.create_namespaced_pod.call_count == 1
    assert process.run.call_count == 1


def test_arbitrary_http_200_is_not_jupyter_readiness(startup):
    backend, owner, profile, api, _, _, _, tls = startup
    tls.http.get.return_value.json.return_value = {'status': 'ok'}
    with pytest.raises(RuntimeError, match='Jupyter'):
        backend.ensure_system(owner, profile)
    assert not backend._connections
    tls.close.assert_called_once()
    api.delete_namespaced_pod.assert_not_called()


def test_readiness_wait_is_bounded_and_never_recreates_pods(startup):
    from requests.exceptions import ConnectionError

    backend, owner, profile, api, _, _, _, tls = startup
    backend.startup_timeout = 0.04
    tls.http.get.side_effect = ConnectionError('Endpoint unavailable')
    with pytest.raises(TimeoutError):
        backend.ensure_system(owner, profile)
    assert api.create_namespaced_pod.call_count == 1
    assert not backend._connections
    tls.close.assert_called_once()


def test_certificate_failure_is_never_treated_as_service_publication_lag(startup):
    from requests.exceptions import SSLError

    backend, owner, profile, _, _, _, _, tls = startup
    tls.http.get.side_effect = SSLError('Wrong pinned certificate')
    with pytest.raises(SSLError):
        backend.ensure_system(owner, profile)
    assert tls.http.get.call_count == 1
    tls.close.assert_called_once()


@pytest.mark.parametrize('field', ['uid', 'ip', 'unbound', 'rwo'])
def test_unverified_identity_or_storage_never_creates_execution_resources(startup, field):
    backend, owner, profile, api, runtime, _, _, _ = startup
    if field == 'uid':
        runtime['metadata']['uid'] = 'foreign'
    elif field == 'ip':
        runtime['status']['podIP'] = '10.0.0.2'
    elif field == 'unbound':
        api.read_namespaced_persistent_volume_claim.return_value['status']['phase'] = 'Pending'
    else:
        api.read_namespaced_persistent_volume_claim.return_value['spec']['accessModes'] = ['ReadWriteOnce']
    with pytest.raises(RuntimeError):
        backend.ensure_system(owner, profile)
    api.create_namespaced_pod.assert_not_called()
    api.create_namespaced_service.assert_not_called()


def test_failed_pinned_readiness_closes_trust_without_deleting_ambiguous_resources(startup):
    backend, owner, profile, api, _, _, _, tls = startup
    tls.http.get.side_effect = RuntimeError('certificate mismatch')
    with pytest.raises(RuntimeError, match='certificate mismatch'):
        backend.ensure_system(owner, profile)
    tls.close.assert_called_once()
    api.delete_namespaced_pod.assert_not_called()
    assert not backend._connections


def test_restarted_container_invalidates_cached_trust_and_never_resumes_old_kernel(startup):
    backend, owner, profile, api, _, pod, _, tls = startup
    backend.ensure_system(owner, profile)
    pod['status']['containerStatuses'][0]['containerID'] = 'container-b'
    with pytest.raises(SandboxGenerationChangedError):
        backend.ensure_system(owner, profile)
    tls.close.assert_called_once()
    assert not backend._connections
    assert api.create_namespaced_pod.call_count == 1


def test_permission_preflight_failure_precedes_any_kubernetes_operation(startup):
    backend, owner, profile, api, _, _, _, _ = startup
    backend.verify_workspace = Mock(side_effect=RuntimeError('unsafe claim permissions'))
    with pytest.raises(RuntimeError, match='unsafe claim'):
        backend.ensure_system(owner, profile)
    api.read_namespaced_pod.assert_not_called()


def test_owner_intent_write_failure_precedes_any_resource_mutation(startup):
    backend, owner, profile, api, _, _, _, _ = startup
    backend.resource_events = Mock()
    backend.resource_events.creation_intent.side_effect = RuntimeError('owner facts unavailable')
    with pytest.raises(RuntimeError, match='owner facts'):
        backend.ensure_system(owner, profile)
    api.create_namespaced_service.assert_not_called()
    api.create_namespaced_pod.assert_not_called()


def test_ready_fact_failure_never_publishes_a_usable_connection(startup):
    backend, owner, profile, _, _, _, _, tls = startup
    backend.resource_events = Mock()
    backend.resource_events.observe_pod.side_effect = [None, RuntimeError('ready facts unavailable')]
    with pytest.raises(RuntimeError, match='ready facts'):
        backend.ensure_system(owner, profile)
    assert not backend._connections
    tls.close.assert_called_once()
