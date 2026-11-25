# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Inject trusted Kubernetes clients and process-local callback ownership."""

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from runtime.sandbox_workspace import KubernetesWorkspace

from nexent.core.agents.sandbox_callbacks import SandboxCallbackRegistry
from nexent.core.agents.sandbox_kubernetes import KubernetesSandboxBackend


@contextmanager
def kubernetes_api():
    from kubernetes import client, config

    configuration = client.Configuration()
    config.load_incluster_config(client_configuration=configuration)
    with client.ApiClient(configuration) as transport:
        yield client.CoreV1Api(transport)


@lru_cache(maxsize=1)
def get_sandbox_services(owner, profile, workspace_root: str, volume_mount: str, single_node_development=False):
    workspace = KubernetesWorkspace(workspace_root, owner, execution_gid=profile.execution_gid)
    from runtime.sandbox_runtime import get_coordinator

    coordinator = get_coordinator()
    if coordinator is None or coordinator.owner_facts is None:
        raise RuntimeError('Kubernetes execution requires initialized Runtime ownership facts')
    def verify_workspace():
        info = Path(volume_mount).stat()
        if info.st_gid != profile.execution_gid or info.st_mode & 0o2070 != 0o2070:
            raise RuntimeError('Workspace PVC root must have the sandbox group and setgid group access before use')

    backend = KubernetesSandboxBackend(
        kubernetes_api, workspace_subpath=workspace.volume_subpath(volume_mount),
        single_node_development=single_node_development, verify_workspace=verify_workspace,
        resource_events=coordinator.owner_facts,
    )
    callbacks = SandboxCallbackRegistry(owner)
    coordinator.sandbox_backend = backend
    coordinator.sandbox_profile = profile
    return workspace, backend, callbacks


def bind_runtime_sandbox(config, *, execution_run_id=None):
    """Only the backend, never a serialized Agent policy, supplies these objects."""
    from contracts.constants.environment import (
        AGENT_WORKSPACE_ROOT,
        NEXENT_SANDBOX_SINGLE_NODE_DEVELOPMENT,
        NEXENT_SANDBOX_WORKSPACE_MOUNT,
    )

    workspace, backend, callbacks = get_sandbox_services(
        config.owner, config.system_profile, AGENT_WORKSPACE_ROOT, NEXENT_SANDBOX_WORKSPACE_MOUNT,
        NEXENT_SANDBOX_SINGLE_NODE_DEVELOPMENT,
    )
    config.runtime_backend, config.callback_registry, config.workspace_access = backend, callbacks, workspace
    if execution_run_id is not None:
        from runtime.sandbox_runtime import get_coordinator

        config.run_lifecycle = get_coordinator().lifecycle(execution_run_id)
    host = config.owner.pod_ip
    if ':' in host:
        host = '[' + host + ']'
    config.callback_endpoint = f'http://{host}:5014/internal/sandbox/tool-invoke'
    config.extra_kwargs['workspace_root'] = str(workspace.owner_root)


def current_callback_registry():
    from contracts.constants.environment import (
        AGENT_WORKSPACE_ROOT,
        NEXENT_SANDBOX_SINGLE_NODE_DEVELOPMENT,
        NEXENT_SANDBOX_WORKSPACE_MOUNT,
    )
    from runtime.adapters.nexent.sandbox import get_runtime_sandbox_options

    options = get_runtime_sandbox_options()
    if options.get('provider') != 'kubernetes' or options.get('enabled') is False:
        return None
    return get_sandbox_services(
        options['owner'], options['system_profile'], AGENT_WORKSPACE_ROOT, NEXENT_SANDBOX_WORKSPACE_MOUNT,
        NEXENT_SANDBOX_SINGLE_NODE_DEVELOPMENT,
    )[2]
