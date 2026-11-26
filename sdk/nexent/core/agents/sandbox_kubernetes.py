# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Kubernetes SYSTEM resources with explicit clients and fail-closed ownership."""

from __future__ import annotations

import math
import threading
import time
from concurrent.futures import CancelledError
from pathlib import PurePosixPath
from typing import Any, Callable

from kubernetes.client import ApiClient
from kubernetes.client.exceptions import ApiException
from kubernetes.utils.quantity import parse_quantity
from requests.exceptions import ConnectionError as HTTPConnectionError
from requests.exceptions import SSLError, Timeout as HTTPTimeout

from nexent.core.agents.sandbox_contracts import (
    DEFAULT_PNPM_STORE_PATH,
    SandboxGenerationChangedError,
    SandboxOwner,
    SandboxPreExecutionError,
    SystemSandboxProfile,
)
from nexent.core.agents.sandbox.tls import TLS_BOOTSTRAP, TLS_CERTIFICATE, TLS_DIRECTORY, SandboxTLSClient


_SEED = """from pathlib import Path
import shutil
source = Path('/opt/nexent/pnpm-store')
target = Path('/seed')
if (source / 'v3').is_dir():
    for path in source.rglob('*'):
        if path.is_symlink():
            raise RuntimeError('Unexpected symlink in pnpm seed')
    for path in source.iterdir():
        if path.is_dir():
            shutil.copytree(path, target / path.name)
        else:
            shutil.copy2(path, target / path.name)
    for path in target.rglob('*'):
        if path.is_symlink():
            raise RuntimeError('Unexpected symlink in pnpm seed')
        path.chmod(0o555 if path.is_dir() else 0o444)
"""


def _document(value: Any) -> dict:
    with ApiClient() as serializer:
        return serializer.sanitize_for_serialization(value)


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _contains(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _contains(a, e) for a, e in zip(actual, expected)
        )
    return actual == expected


def _conflict_paths(actual: Any, expected: Any, path: str = '') -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        return [p for k, v in expected.items()
                for p in _conflict_paths(actual.get(k), v, path + '/' + k)]
    if isinstance(expected, list) and isinstance(actual, list) and len(actual) == len(expected):
        return [p for i, (a, e) in enumerate(zip(actual, expected)) for p in _conflict_paths(a, e, f'{path}/{i}')]
    return [] if actual == expected else [path]


def sandbox_container_terminated(pod, pod_uid, container_id=None):
    if pod.get('metadata', {}).get('uid') != pod_uid:
        return False
    for status in pod.get('status', {}).get('containerStatuses', []):
        if status.get('name') != 'sandbox':
            continue
        states = [status.get('state', {})]
        if container_id is not None:
            states.append(status.get('lastState', {}))
        for state in states:
            terminated = state.get('terminated', {})
            identity = terminated.get('containerID')
            if state is states[0]:
                identity = identity or status.get('containerID')
            if terminated.get('finishedAt') and (container_id is None or identity == container_id):
                return True
    return False


def wait_for_sandbox_termination(api, namespace, pod, deadline, *, container_id=None):
    """Read watch history from the observed version; DELETED alone proves nothing."""
    from kubernetes.watch import Watch

    metadata = pod['metadata']
    if sandbox_container_terminated(pod, metadata['uid'], container_id):
        return True
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not metadata.get('resourceVersion'):
        return False
    watch = Watch()
    events = watch.stream(
        api.list_namespaced_pod, namespace, field_selector='metadata.name=' + metadata['name'],
        resource_version=metadata['resourceVersion'], timeout_seconds=max(1, math.ceil(remaining)),
        _request_timeout=(min(2, remaining), remaining),
    )
    try:
        for event in events:
            observed = event.get('raw_object') or _document(event['object'])
            if sandbox_container_terminated(observed, metadata['uid'], container_id):
                return True
            if time.monotonic() >= deadline:
                return False
        return False
    finally:
        watch.stop()
        events.close()


class KubernetesGateway:
    """A borrowed connection whose trust is bound to one Pod/container generation."""

    _nexent_backend = 'kubernetes'

    def __init__(self, backend, owner, profile, pod, certificate):
        self.backend, self.owner, self.profile = backend, owner, profile
        self.generation = backend.generation(pod)
        self.pod_uid = pod['metadata']['uid']
        self.container_id = next(s['containerID'] for s in pod['status']['containerStatuses'] if s['name'] == 'sandbox')
        self.host = backend.service_host(owner)
        self.port = 8080
        self.base_url = f'https://{self.host}:{self.port}'
        self.tls_client = SandboxTLSClient(certificate)
        self.additional_imports: list[str] = []
        self.installed_packages: list[str] = []

    def assert_generation(self, *, deadline=None):
        timeout = 10 if deadline is None else min(10, deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError('Sandbox generation verification deadline exceeded')
        with self.backend.api_factory() as api:
            pod = _document(api.read_namespaced_pod(
                self.backend.resource_name(self.owner), self.owner.namespace, _request_timeout=timeout,
            ))
        self.backend.validate_resource(pod, self.backend.manifests(self.owner, self.profile)[0])
        if self.backend.generation(pod) != self.generation:
            raise SandboxGenerationChangedError('Sandbox container generation changed; execution cannot resume')

    def close(self):
        self.tls_client.close()

    def cleanup(self):
        self.backend.close_owner(self.owner, self.profile)


class KubernetesSandboxBackend:
    """Manage deterministic resources; API facts, never process caches, establish identity.

    The injected factory returns a context-managed CoreV1Api. Each exec must use
    a separate ApiClient because Kubernetes stream temporarily changes its transport.
    No user policy or model argument can provide management credentials or subpaths.
    """

    def __init__(self, api_factory: Callable, *, workspace_subpath: str, startup_timeout: float = 120,
                 single_node_development: bool = False, verify_workspace=lambda: None, resource_events=None):
        path = PurePosixPath(workspace_subpath)
        if (not workspace_subpath or path.is_absolute() or '..' in path.parts
                or '\\' in workspace_subpath or ':' in workspace_subpath):
            raise ValueError('Sandbox requires a trusted relative owner workspace subpath')
        if type(startup_timeout) not in (int, float) or not math.isfinite(startup_timeout) or startup_timeout <= 0:
            raise ValueError('Sandbox startup timeout must be positive')
        if type(single_node_development) is not bool:
            raise ValueError('Single-node development must be an explicit boolean')
        self.api_factory = api_factory
        self.workspace_subpath = workspace_subpath
        self.startup_timeout = startup_timeout
        self.single_node_development = single_node_development
        self.verify_workspace = verify_workspace
        self.resource_events = resource_events
        self._development_nodes: dict[str, str] = {}
        self._pull_secrets: dict[str, list] = {}
        self._lock = threading.Lock()
        self._connections: dict[str, KubernetesGateway] = {}
        self._closed = False

    @staticmethod
    def resource_name(owner: SandboxOwner) -> str:
        return 'nexent-sandbox-' + owner.key[:40]

    def service_host(self, owner: SandboxOwner) -> str:
        return f'{self.resource_name(owner)}.{owner.namespace}.svc'

    def manifests(self, owner: SandboxOwner, profile: SystemSandboxProfile) -> tuple[dict, dict]:
        name = self.resource_name(owner)
        labels = {'nexent.ai/sandbox': 'system', 'nexent.ai/owner': owner.key[:40],
                  'nexent.ai/network': 'offline' if profile.network_disabled else 'online'}
        metadata = {'name': name, 'namespace': owner.namespace, 'labels': labels,
                    'annotations': {'nexent.ai/profile': profile.fingerprint, 'nexent.ai/epoch': owner.epoch},
                    'ownerReferences': [{'apiVersion': 'v1', 'kind': 'Pod', 'name': owner.pod_name,
                                         'uid': owner.pod_uid, 'controller': True, 'blockOwnerDeletion': False}]}
        security = {'allowPrivilegeEscalation': False, 'privileged': False, 'capabilities': {'drop': ['ALL']}}
        command = ['python', '-c', TLS_BOOTSTRAP, self.service_host(owner), TLS_DIRECTORY,
                   'jupyter', 'kernelgateway', f'--KernelGatewayApp.certfile={TLS_CERTIFICATE}',
                   f'--KernelGatewayApp.keyfile={TLS_DIRECTORY}/server.key', '--KernelGatewayApp.ip=0.0.0.0',
                   '--KernelGatewayApp.port=8080', '--KernelGatewayApp.allow_origin=*',
                   '--ServerApp.allow_remote_access=True', '--JupyterWebsocketPersonality.list_kernels=True']
        pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': metadata, 'spec': {
            'automountServiceAccountToken': False, 'restartPolicy': 'Never', 'enableServiceLinks': False,
            'hostNetwork': False, 'hostPID': False, 'hostIPC': False,
            'securityContext': {'runAsNonRoot': True, 'runAsUser': profile.execution_uid,
                                'runAsGroup': profile.execution_gid, 'fsGroup': profile.execution_gid,
                                'fsGroupChangePolicy': 'OnRootMismatch', 'seccompProfile': {'type': 'RuntimeDefault'}},
            'containers': [{'name': 'sandbox', 'image': profile.execution_image, 'imagePullPolicy': 'IfNotPresent',
                            'command': command, 'securityContext': security,
                            'resources': {'limits': {'memory': f'{profile.memory_limit_mb}Mi',
                                                     'cpu': str(profile.cpu_quota)}},
                            'ports': [{'containerPort': 8080, 'name': 'gateway'}],
                            'volumeMounts': [
                                {'name': 'workspace', 'mountPath': profile.container_workspace_root,
                                 'subPath': self.workspace_subpath, 'readOnly': False},
                                {'name': 'pnpm-seed', 'mountPath': DEFAULT_PNPM_STORE_PATH,
                                 'readOnly': True}],
                            'readinessProbe': {'tcpSocket': {'port': 8080}, 'periodSeconds': 2}}],
            'initContainers': [{'name': 'pnpm-seed', 'image': profile.execution_image,
                                'imagePullPolicy': 'IfNotPresent', 'command': ['python', '-c', _SEED],
                                'securityContext': security,
                                'volumeMounts': [{'name': 'pnpm-seed', 'mountPath': '/seed', 'readOnly': False}]}],
            'volumes': [{'name': 'workspace', 'persistentVolumeClaim': {'claimName': profile.workspace_volume}},
                        {'name': 'pnpm-seed', 'emptyDir': {}}],
        }}
        if self.single_node_development and owner.key in self._development_nodes:
            pod['spec']['nodeName'] = self._development_nodes[owner.key]
        if self._pull_secrets.get(owner.key):
            pod['spec']['imagePullSecrets'] = self._pull_secrets[owner.key]
        service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': metadata, 'spec': {
            'type': 'ClusterIP', 'selector': {'nexent.ai/owner': owner.key[:40], 'nexent.ai/sandbox': 'system'},
            'ports': [{'name': 'gateway', 'port': 8080, 'targetPort': 8080, 'protocol': 'TCP'}],
        }}
        return pod, service

    @staticmethod
    def validate_resource(actual: dict, expected: dict, *, allow_deleting=False) -> None:
        # Kubernetes canonicalizes resource quantities (for example 1.0 to 1).
        from copy import deepcopy

        actual, expected = deepcopy(actual), deepcopy(expected)
        for document in (actual, expected):
            spec = document.get('spec', {})
            if document.get('kind') == 'Pod':
                for flag in ('hostNetwork', 'hostPID', 'hostIPC'):
                    spec.setdefault(flag, False)
            for container in spec.get('containers', []) + spec.get('initContainers', []):
                for mount in container.get('volumeMounts', []):
                    mount.setdefault('readOnly', False)
                for name, quantity in container.get('resources', {}).get('limits', {}).items():
                    if name in ('cpu', 'memory'):
                        container['resources']['limits'][name] = parse_quantity(quantity)
        if (actual.get('metadata', {}).get('deletionTimestamp') and not allow_deleting) or not _contains(actual, expected):
            paths = ','.join(_conflict_paths(actual, expected))
            raise RuntimeError(f'Kubernetes sandbox resource ownership/profile conflict at {paths}; resource preserved')

    def create_or_confirm(self, api, kind: str, namespace: str, manifest: dict) -> dict:
        """A lost response never allocates an alternative resource or authorizes deletion."""
        try:
            resource = getattr(api, f'create_namespaced_{kind}')(namespace, manifest, _request_timeout=10)
        except Exception:
            try:
                resource = getattr(api, f'read_namespaced_{kind}')(
                    manifest['metadata']['name'], namespace, _request_timeout=10,
                )
            except Exception as exc:
                raise RuntimeError('Sandbox creation unresolved; retry must reconcile the same resource name') from exc
        resource = _document(resource)
        self.validate_resource(resource, manifest)
        return resource

    @staticmethod
    def generation(pod: dict) -> str:
        statuses = pod.get('status', {}).get('containerStatuses', [])
        current = next((s for s in statuses if s['name'] == 'sandbox'), {})
        if not current.get('state', {}).get('running') or not current.get('containerID'):
            raise SandboxGenerationChangedError('Sandbox container generation is no longer running')
        return f"{pod['metadata']['uid']}:{current['containerID']}:{current.get('restartCount', 0)}"

    def ensure_system(self, owner: SandboxOwner, profile: SystemSandboxProfile, *, check_cancelled=lambda: None):
        deadline = time.monotonic() + self.startup_timeout
        while not self._lock.acquire(timeout=0.1):
            check_cancelled()
            if time.monotonic() >= deadline:
                raise TimeoutError('Sandbox acquisition lock timed out')
        try:
            check_cancelled()
            if self._closed:
                raise CancelledError('Sandbox backend is closing')
            existing = self._connections.get(owner.key)
            if existing:
                if existing.owner != owner or existing.profile != profile:
                    raise RuntimeError('Sandbox SYSTEM profile/epoch conflict')
                try:
                    existing.assert_generation()
                except SandboxGenerationChangedError:
                    existing.close()
                    self._connections.pop(owner.key, None)
                    raise
                if self.resource_events is not None:
                    self.resource_events.observe_pod(owner, existing.pod_uid, existing.container_id, ready=True)
                check_cancelled()
                return existing
            try:
                self.verify_workspace()
            except Exception as exc:
                if (self.resource_events is not None
                        and self.resource_events.permits_pre_execution_fallback(owner)):
                    raise SandboxPreExecutionError('Workspace preflight failed before any execution intent') from exc
                raise
            with self.api_factory() as api:
                runtime = _document(api.read_namespaced_pod(owner.pod_name, owner.namespace, _request_timeout=10))
                if (runtime['metadata']['uid'] != owner.pod_uid or runtime.get('metadata', {}).get('deletionTimestamp')
                        or runtime.get('status', {}).get('podIP') != owner.pod_ip):
                    raise RuntimeError('Runtime Pod identity cannot be verified')
                self._pull_secrets[owner.key] = runtime.get('spec', {}).get('imagePullSecrets', [])
                claim = _document(api.read_namespaced_persistent_volume_claim(
                    profile.workspace_volume, owner.namespace, _request_timeout=10,
                ))
                if claim.get('status', {}).get('phase') != 'Bound':
                    raise RuntimeError('Sandbox workspace claim is not Bound')
                if not self.single_node_development and 'ReadWriteMany' not in claim.get('spec', {}).get('accessModes', []):
                    raise RuntimeError('Sandbox requires verified cross-node CSI RWX storage')
                if self.single_node_development:
                    node = runtime.get('spec', {}).get('nodeName')
                    if not node:
                        raise RuntimeError('Single-node development requires the actual Runtime node')
                    self._development_nodes[owner.key] = node
                pod_manifest, service_manifest = self.manifests(owner, profile)
                if self.resource_events is not None:
                    self.resource_events.creation_intent(owner, profile, self.resource_name(owner))
                check_cancelled()
                self.create_or_confirm(api, 'service', owner.namespace, service_manifest)
                check_cancelled()
                pod = self.create_or_confirm(api, 'pod', owner.namespace, pod_manifest)
                expected_uid = pod['metadata']['uid']
                if self.resource_events is not None:
                    self.resource_events.observe_pod(owner, expected_uid)
                while True:
                    check_cancelled()
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Sandbox readiness deadline exceeded; owned resource preserved')
                    pod = _document(api.read_namespaced_pod(
                        self.resource_name(owner), owner.namespace, _request_timeout=10,
                    ))
                    self.validate_resource(pod, pod_manifest)
                    if pod['metadata']['uid'] != expected_uid:
                        raise RuntimeError('Sandbox Pod UID changed during startup')
                    if pod.get('status', {}).get('phase') in ('Failed', 'Succeeded'):
                        raise RuntimeError('Sandbox terminated during startup; reconcile before retrying')
                    ready = any(c.get('type') == 'Ready' and c.get('status') == 'True'
                                for c in pod.get('status', {}).get('conditions', []))
                    if ready:
                        break
                    time.sleep(0.1)
            from nexent.core.agents.sandbox_kubernetes_exec import KubernetesProcessAdapter

            generation = self.generation(pod)
            process = KubernetesProcessAdapter(self, owner, profile, generation, check_cancelled=check_cancelled)
            result = process.run(['cat', TLS_CERTIFICATE], cwd='/home/sandbox', env={},
                                 timeout_seconds=max(0.1, min(10, deadline - time.monotonic())))
            if result.exit_code or len(result.stdout) > 16384:
                raise RuntimeError('Sandbox public certificate could not be obtained over trusted exec')
            connection = KubernetesGateway(self, owner, profile, pod, result.stdout)
            try:
                self._wait_pinned_jupyter(connection, deadline, check_cancelled)
                if self.resource_events is not None:
                    self.resource_events.observe_pod(owner, connection.pod_uid, connection.container_id, ready=True)
                check_cancelled()
            except BaseException:
                connection.close()
                raise
            self._connections[owner.key] = connection
            return connection
        finally:
            self._lock.release()

    @staticmethod
    def _wait_pinned_jupyter(connection, deadline, check_cancelled):
        while True:
            check_cancelled()
            connection.assert_generation(deadline=deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Sandbox pinned Jupyter readiness deadline exceeded')
            response = None
            try:
                # Pod readiness precedes EndpointSlice/Service publication. Only
                # this side-effect-free GET may retry; kernel/code requests may not.
                response = connection.tls_client.http.get(connection.base_url + '/api/kernels',
                                                           timeout=min(2, remaining))
                if response.status_code == 200:
                    kernels = response.json()
                    if not isinstance(kernels, list) or any(
                            not isinstance(item, dict) or not isinstance(item.get('id'), str) for item in kernels):
                        raise RuntimeError('Sandbox response is not Jupyter kernel readiness')
                    return
                if response.status_code not in {502, 503, 504}:
                    raise RuntimeError('Sandbox pinned HTTPS readiness failed')
            except SSLError:
                raise
            except (HTTPConnectionError, HTTPTimeout):
                pass
            finally:
                if response is not None:
                    response.close()
            check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Sandbox pinned Jupyter readiness deadline exceeded')
            time.sleep(min(0.1, remaining))

    def close_owner(self, owner: SandboxOwner, profile: SystemSandboxProfile, *, deadline=None) -> None:
        """Call only after admission/drain, never as an individual lease cleanup."""
        deadline = time.monotonic() + 10 if deadline is None else deadline
        if not self._lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise TimeoutError('Sandbox owner cleanup lock deadline exceeded')
        try:
            self._closed = True
            connection = self._connections.pop(owner.key, None)
            if connection:
                connection.close()
            pod_manifest, service_manifest = self.manifests(owner, profile)
            with self.api_factory() as api:
                failure = None
                for kind, expected in [('pod', pod_manifest), ('service', service_manifest)]:
                    try:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError('Sandbox owner cleanup deadline exceeded')
                        actual = _document(getattr(api, f'read_namespaced_{kind}')(
                            self.resource_name(owner), owner.namespace, _request_timeout=min(5, remaining),
                        ))
                        self.validate_resource(actual, expected, allow_deleting=True)
                        getattr(api, f'delete_namespaced_{kind}')(
                            self.resource_name(owner), owner.namespace,
                            body={'preconditions': {'uid': actual['metadata']['uid']},
                                  **({'gracePeriodSeconds': min(2, max(0, int(remaining) - 1))}
                                     if kind == 'pod' else {})},
                            _request_timeout=max(0.1, min(5, deadline - time.monotonic())),
                        )
                        if kind == 'pod' and self.resource_events is not None:
                            if not wait_for_sandbox_termination(
                                api, owner.namespace, actual, deadline,
                                container_id=connection.container_id if connection else None,
                            ):
                                raise RuntimeError('Sandbox termination is unproved; owner facts remain unknown')
                            self.resource_events.terminated(owner, actual['metadata']['uid'])
                    except ApiException as exc:
                        if exc.status != 404:
                            failure = exc
                        elif self.resource_events is not None:
                            try:
                                self.resource_events.missing(owner, kind)
                            except Exception as missing:
                                failure = missing
                    except Exception as exc:
                        failure = exc
                if failure is not None:
                    raise failure
        finally:
            self._lock.release()
