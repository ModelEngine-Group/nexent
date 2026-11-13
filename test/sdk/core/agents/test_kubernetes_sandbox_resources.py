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


def test_uncertain_creation_is_not_deleted_or_retried(resources):
    api, owner, profile, backend = resources
    pod, _ = backend.manifests(owner, profile)
    api.create_namespaced_pod.side_effect = ApiException(status=500)
    api.read_namespaced_pod.side_effect = ApiException(status=503)
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
