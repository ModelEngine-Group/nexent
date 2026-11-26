# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resource ownership tests; live Kubernetes acceptance is a separate suite."""

from copy import deepcopy
from unittest.mock import MagicMock, Mock

import pytest
from kubernetes.client.exceptions import ApiException

from nexent.core.agents.sandbox_contracts import SandboxOwner, SystemSandboxProfile
from nexent.core.agents.sandbox_kubernetes import KubernetesSandboxBackend


@pytest.fixture
def resources():
    api = MagicMock()
    api.__enter__.return_value = api
    owner = SandboxOwner('release', 'test', 'runtime-a', 'uid-a', '10.0.0.1', 'epoch-a')
    profile = SystemSandboxProfile('sandbox:verified', 'workspace')
    backend = KubernetesSandboxBackend(lambda: api, workspace_subpath='workdir/owners/uid-a')
    return api, owner, profile, backend


def test_deterministic_name_uses_full_owner_and_not_epoch(resources):
    _, owner, _, backend = resources
    other_epoch = SandboxOwner('release', 'test', 'runtime-a', 'uid-a', '10.0.0.2', 'epoch-b')
    other_uid = SandboxOwner('release', 'test', 'runtime-a', 'uid-b', '10.0.0.1', 'epoch-a')
    assert backend.resource_name(owner) == backend.resource_name(other_epoch)
    assert backend.resource_name(owner) != backend.resource_name(other_uid)
    assert len(backend.resource_name(owner)) <= 63


def test_manifest_is_nonroot_scoped_and_has_full_seed(resources):
    _, owner, profile, backend = resources
    pod, service = backend.manifests(owner, profile)
    spec = pod['spec']
    assert spec['automountServiceAccountToken'] is False
    assert spec['securityContext']['runAsUser'] == 1000
    assert spec['restartPolicy'] == 'Never'
    assert pod['metadata']['ownerReferences'][0]['uid'] == owner.pod_uid
    assert service['metadata']['ownerReferences'] == pod['metadata']['ownerReferences']
    assert spec['containers'][0]['image'] == spec['initContainers'][0]['image'] == profile.execution_image
    assert spec['containers'][0]['securityContext']['capabilities'] == {'drop': ['ALL']}
    assert spec['volumes'][0]['persistentVolumeClaim']['claimName'] == 'workspace'
    mount = spec['containers'][0]['volumeMounts'][0]
    assert mount['subPath'] == 'workdir/owners/uid-a'
    assert any(m['name'] == 'pnpm-seed' and m['readOnly'] for m in spec['containers'][0]['volumeMounts'])
    assert not any(v.get('hostPath') for v in spec['volumes'])


def test_custom_workspace_keeps_the_existing_image_pnpm_store_location(resources):
    from dataclasses import replace

    _, owner, profile, backend = resources
    pod, _ = backend.manifests(owner, replace(profile, container_workspace_root='/custom/workdir'))
    mounts = pod['spec']['containers'][0]['volumeMounts']
    assert next(m for m in mounts if m['name'] == 'workspace')['mountPath'] == '/custom/workdir'
    assert next(m for m in mounts if m['name'] == 'pnpm-seed')['mountPath'] == '/mnt/nexent/workdir/.pnpm-store'


@pytest.mark.parametrize('change', ['uid', 'profile', 'epoch', 'image', 'privileged', 'mount'])
def test_foreign_or_modified_resource_is_not_adopted(resources, change):
    _, owner, profile, backend = resources
    expected, _ = backend.manifests(owner, profile)
    actual = deepcopy(expected)
    if change == 'uid':
        actual['metadata']['ownerReferences'][0]['uid'] = 'foreign'
    elif change in ('profile', 'epoch'):
        actual['metadata']['annotations']['nexent.ai/' + change] = 'foreign'
    elif change == 'image':
        actual['spec']['containers'][0]['image'] = 'other:image'
    elif change == 'privileged':
        actual['spec']['containers'][0]['securityContext']['privileged'] = True
    else:
        actual['spec']['containers'][0]['volumeMounts'][0]['subPath'] = 'workdir'
    with pytest.raises(RuntimeError, match='conflict'):
        backend.validate_resource(actual, expected)


@pytest.mark.parametrize('status', [409, 500, 0])
def test_lost_create_response_reads_same_name_without_duplicate(resources, status):
    api, owner, profile, backend = resources
    pod, _ = backend.manifests(owner, profile)
    pod['metadata']['uid'] = 'sandbox-uid'
    api.create_namespaced_pod.side_effect = ApiException(status=status)
    api.read_namespaced_pod.return_value = pod
    result = backend.create_or_confirm(api, 'pod', owner.namespace, pod)
    assert result['metadata']['uid'] == 'sandbox-uid'
    assert api.create_namespaced_pod.call_count == 1
    api.read_namespaced_pod.assert_called_once_with(pod['metadata']['name'], owner.namespace, _request_timeout=10)


@pytest.mark.parametrize("lookup_status", [404, 503])
def test_unconfirmed_creation_is_not_deleted_or_retried(resources, lookup_status):
    api, owner, profile, backend = resources
    pod, _ = backend.manifests(owner, profile)
    api.create_namespaced_pod.side_effect = ApiException(status=500)
    api.read_namespaced_pod.side_effect = ApiException(status=lookup_status)
    with pytest.raises(RuntimeError, match='unresolved'):
        backend.create_or_confirm(api, 'pod', owner.namespace, pod)
    api.delete_namespaced_pod.assert_not_called()
    assert api.create_namespaced_pod.call_count == 1


@pytest.mark.parametrize('path', ['', '/workdir', '../workdir', 'workdir/../owners', 'workdir\\owners'])
def test_invalid_subpath_rejected(path):
    with pytest.raises(ValueError):
        KubernetesSandboxBackend(Mock(), workspace_subpath=path)


def test_shutdown_deletes_uid_matched_resources_and_not_claim(resources):
    api, owner, profile, backend = resources
    pod, service = backend.manifests(owner, profile)
    pod, service = deepcopy(pod), deepcopy(service)
    pod['metadata']['uid'], service['metadata']['uid'] = 'pod-uid', 'service-uid'
    api.read_namespaced_pod.return_value = pod
    api.read_namespaced_service.return_value = service
    backend.close_owner(owner, profile)
    assert api.delete_namespaced_pod.call_args.kwargs['body']['preconditions']['uid'] == 'pod-uid'
    assert api.delete_namespaced_service.call_args.kwargs['body']['preconditions']['uid'] == 'service-uid'
    api.delete_namespaced_persistent_volume_claim.assert_not_called()


@pytest.mark.parametrize('proved', [False, True])
def test_shutdown_reports_retirement_only_after_execution_termination(resources, monkeypatch, proved):
    import nexent.core.agents.sandbox_kubernetes as module

    api, owner, profile, backend = resources
    pod, service = backend.manifests(owner, profile)
    pod, service = deepcopy(pod), deepcopy(service)
    pod['metadata']['uid'], service['metadata']['uid'] = 'pod-uid', 'service-uid'
    api.read_namespaced_pod.return_value, api.read_namespaced_service.return_value = pod, service
    events, connection = Mock(), Mock(container_id='cid')
    backend.resource_events = events
    backend._connections[owner.key] = connection
    monkeypatch.setattr(module, 'wait_for_sandbox_termination', Mock(return_value=proved))
    if proved:
        backend.close_owner(owner, profile)
        events.terminated.assert_called_once_with(owner, 'pod-uid')
    else:
        with pytest.raises(RuntimeError, match='termination is unproved'):
            backend.close_owner(owner, profile)
        events.terminated.assert_not_called()
    connection.close.assert_called_once()
    api.delete_namespaced_service.assert_called_once()
    api.delete_namespaced_persistent_volume_claim.assert_not_called()


@pytest.mark.parametrize('status,missing_fails', [(404, False), (404, True), (403, False)])
def test_shutdown_preserves_ownership_failure_even_when_objects_are_missing(resources, status, missing_fails):
    api, owner, profile, backend = resources
    events = backend.resource_events = Mock()
    api.read_namespaced_pod.side_effect = ApiException(status=status)
    api.read_namespaced_service.side_effect = ApiException(status=status)
    if missing_fails:
        events.missing.side_effect = RuntimeError('unknown execution')
    if status == 403 or missing_fails:
        with pytest.raises((ApiException, RuntimeError)):
            backend.close_owner(owner, profile)
    else:
        backend.close_owner(owner, profile)
        assert [call.args[1] for call in events.missing.call_args_list] == ['pod', 'service']
    api.delete_namespaced_pod.assert_not_called()
    api.delete_namespaced_service.assert_not_called()


def test_expired_shutdown_deadline_does_not_delete_resources(resources):
    api, owner, profile, backend = resources
    with pytest.raises(TimeoutError):
        backend.close_owner(owner, profile, deadline=0)
    api.delete_namespaced_pod.assert_not_called()
    assert not backend._lock.locked()


@pytest.mark.parametrize('failure', ['generation', 'profile', 'closing'])
def test_cached_gateway_conflicts_are_not_adopted_or_recreated(resources, failure):
    from concurrent.futures import CancelledError
    from nexent.core.agents.sandbox_contracts import SandboxGenerationChangedError

    api, owner, profile, backend = resources
    existing = Mock(owner=owner, profile=profile, assert_generation=Mock())
    backend._connections[owner.key] = existing
    if failure == 'generation':
        existing.assert_generation.side_effect = SandboxGenerationChangedError('changed')
    elif failure == 'profile':
        existing.profile = object()
    else:
        backend._closed = True
    with pytest.raises((RuntimeError, CancelledError)):
        backend.ensure_system(owner, profile)
    if failure == 'generation':
        existing.close.assert_called_once()
        assert owner.key not in backend._connections
    api.create_namespaced_pod.assert_not_called()


@pytest.mark.parametrize('safe_to_fallback', [False, True])
def test_workspace_preflight_fallback_requires_unused_protected_owner(resources, safe_to_fallback):
    from nexent.core.agents.sandbox_contracts import SandboxPreExecutionError

    api, owner, profile, backend = resources
    backend.verify_workspace = Mock(side_effect=OSError('workspace unavailable'))
    backend.resource_events = Mock()
    backend.resource_events.permits_pre_execution_fallback.return_value = safe_to_fallback
    with pytest.raises(SandboxPreExecutionError if safe_to_fallback else OSError):
        backend.ensure_system(owner, profile)
    backend.resource_events.creation_intent.assert_not_called()
    api.create_namespaced_pod.assert_not_called()


@pytest.mark.parametrize('status,kernels', [(401, []), (200, {}), (200, [{}])])
def test_pinned_readiness_rejects_unexpected_service_response(resources, status, kernels):
    import time

    _, _, _, backend = resources
    connection = Mock(assert_generation=Mock())
    connection.base_url = 'https://owned'
    response = connection.tls_client.http.get.return_value
    response.status_code, response.json.return_value = status, kernels
    with pytest.raises(RuntimeError):
        backend._wait_pinned_jupyter(connection, time.monotonic() + 10, lambda: None)
    response.close.assert_called_once()
    connection.tls_client.http.get.assert_called_once()
