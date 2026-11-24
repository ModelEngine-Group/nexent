# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Kubernetes Runtime protocol wiring; Docker keeps its existing local ownership."""

import time
from functools import lru_cache
from pathlib import Path

from runtime.identity import PROCESS_EPOCH
from runtime.sandbox_coordination import SandboxRunCoordinator
from runtime.sandbox_journal import SandboxRunJournal
from runtime.sandbox_owner import SandboxOwnerFacts, process_identity

from nexent.core.agents.sandbox_contracts import SandboxOwner
from nexent.core.concurrency import ManagedThreadSpec


@lru_cache(maxsize=1)
def _coordinator(owner, root, workspace_root, redis_client):
    return SandboxRunCoordinator(redis_client, SandboxRunJournal(Path(root) / '.sandbox-control'), owner,
                                  lease_seconds=30, workspace_root=workspace_root)


def get_coordinator():
    from contracts.constants import environment as settings

    if settings.NEXENT_SANDBOX_PROVIDER != 'kubernetes' or not settings.IS_DEPLOYED_BY_KUBERNETES:
        return None
    from infrastructure.redis.run_state import runtime_state_service

    owner = SandboxOwner(
        settings.NEXENT_RUNTIME_DEPLOYMENT_ID, settings.NEXENT_RUNTIME_POD_NAMESPACE,
        settings.NEXENT_RUNTIME_POD_NAME, settings.NEXENT_RUNTIME_POD_UID,
        settings.NEXENT_RUNTIME_POD_IP, PROCESS_EPOCH,
    )
    return _coordinator(owner, settings.NEXENT_SANDBOX_WORKSPACE_MOUNT, settings.AGENT_WORKSPACE_ROOT,
                         runtime_state_service.client)


def initialize_sandbox_coordination(manager):
    """Call during lifespan startup before recovery or business admission."""
    from contracts.constants import environment as settings

    if not settings.NEXENT_SANDBOX_ENABLED:
        return None
    coordinator = get_coordinator()
    if coordinator is None:
        return None
    coordinator.client.ping()
    from runtime.sandbox_services import kubernetes_api

    from nexent.core.agents.sandbox_kubernetes import _document

    deadline = time.monotonic() + 15
    with kubernetes_api() as api:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Runtime container identity was not published before startup deadline')
            pod = _document(api.read_namespaced_pod(coordinator.owner.pod_name, coordinator.owner.namespace,
                                                     _request_timeout=min(2, remaining)))
            if pod['metadata']['uid'] != coordinator.owner.pod_uid:
                raise RuntimeError('Runtime Pod UID differs from the trusted deployment identity')
            status = next((s for s in pod.get('status', {}).get('containerStatuses', [])
                           if s['name'] == settings.NEXENT_RUNTIME_CONTAINER_NAME), {})
            if status.get('containerID') and status.get('state', {}).get('running') is not None:
                break
            time.sleep(min(0.1, remaining))
    facts = SandboxOwnerFacts(coordinator.journal, coordinator.owner)
    facts.initialize(process_identity(status['containerID'], settings.NEXENT_RUNTIME_CONTAINER_NAME))
    coordinator.owner_facts = facts
    from runtime.sandbox_owner import SandboxOwnerObserver
    from runtime.sandbox_recovery import SandboxRuntimeRecovery

    coordinator.recovery = SandboxRuntimeRecovery(
        coordinator, kubernetes_api,
        SandboxOwnerObserver(kubernetes_api, coordinator.owner, facts.read(coordinator.owner.epoch)['process']),
        None, workspace_root=settings.AGENT_WORKSPACE_ROOT,
    )
    coordinator.recovery.recover(startup=True)
    coordinator.recovery.verify_current_owner_resources_absent(time.monotonic() + 10)
    coordinator.claim_owner()
    service = manager.register_service(
        ManagedThreadSpec(task_name='sandbox-run-renewal', owner='runtime', lane='background-service',
                          close_hook=coordinator.cancel_active),
        coordinator.renewal_loop,
    )
    manager.start_service(service.execution_id)
    recovery_service = manager.register_service(
        ManagedThreadSpec(task_name='sandbox-scoped-recovery', owner='runtime', lane='background-service'),
        coordinator.recovery.recovery_loop,
    )
    manager.start_service(recovery_service.execution_id)
    return coordinator
