# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Kubernetes Runtime protocol wiring; Docker keeps its existing local ownership."""

import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from runtime.identity import PROCESS_EPOCH, ensure_request_run_id, reserve_runtime_run, resolve_execution_run_id
from runtime.sandbox_coordination import SandboxRunCoordinator
from runtime.sandbox_journal import SandboxRunJournal
from runtime.sandbox_owner import SandboxOwnerFacts, process_identity
from runtime.sandbox_stream_state import SandboxStreamState

from nexent.core.agents.sandbox_contracts import SandboxOwner
from nexent.core.concurrency import ManagedThreadSpec


@dataclass(frozen=True)
class PreparedRuntimeRun:
    run_id: str
    reservation_token: str
    conversation_id: int | str
    tenant_id: str
    user_id: str
    lease: object
    deferred_run: object
    execution: object
    holder: str = 'automation'


async def begin_automation_admission(tenant_id, user_id, conversation_id, cancel):
    return await begin_owned_agent_admission(tenant_id, user_id, conversation_id, cancel,
                                            kind='AUTOMATION', holder='automation')


async def begin_owned_agent_admission(tenant_id, user_id, conversation_id, cancel, *, kind, holder):
    from infrastructure.concurrency import runtime_thread_manager
    from management.services.agent.lifecycle import agent_run_manager
    from runtime.adapters.nexent.runner import DeferredAgentRun

    from nexent.core.concurrency import ManagedTaskSpec

    coordinator = get_coordinator()
    run_id = resolve_execution_run_id(None)
    deferred = DeferredAgentRun()
    execution = runtime_thread_manager.submit(
        'agent-run', ManagedTaskSpec(task_name=kind.lower() + '-agent-run', owner='runtime', run_id=run_id,
                                     close_hook=deferred.cancel, pass_cancel_event=True),
        deferred.run,
    )
    token = None

    def cancel_owned():
        deferred.cancel()
        cancel()

    try:
        await runtime_thread_manager.wait_until_started(execution)
        token = await reserve_runtime_run(agent_run_manager, conversation_id, user_id, tenant_id=tenant_id,
                                          execution_run_id=run_id, kind=kind, cancel=cancel_owned)
        lease = agent_run_manager.get_distributed_lease(conversation_id, user_id)
        coordinator.hold(lease, holder)
    except BaseException:
        deferred.cancel()
        runtime_thread_manager.cancel(execution.execution_id, reason='automation admission failed', wait_timeout=0,
                                      mark_stuck_on_timeout=False)
        if token is not None:
            agent_run_manager.release_agent_run_reservation(conversation_id, user_id, token)
        raise
    return PreparedRuntimeRun(run_id, token, conversation_id, tenant_id, user_id, lease, deferred, execution, holder)


def finish_automation_admission(admission):
    from management.services.agent.lifecycle import agent_run_manager

    coordinator = get_coordinator()
    if not admission.deferred_run.is_bound:
        admission.deferred_run.cancel()
    agent_run_manager.release_agent_run_reservation(admission.conversation_id, admission.user_id,
                                                    admission.reservation_token)
    coordinator.finish(admission.lease, holder=admission.holder)


@lru_cache(maxsize=1)
def _coordinator(owner, root, workspace_root, redis_client):
    return SandboxRunCoordinator(redis_client, SandboxRunJournal(Path(root) / '.sandbox-control'), owner,
                                  lease_seconds=30, workspace_root=workspace_root)


def get_coordinator():
    from contracts.constants import environment as settings

    if settings.NEXENT_SANDBOX_PROVIDER != 'kubernetes' or not settings.IS_DEPLOYED_BY_KUBERNETES:
        return None
    from management.services.agent.run_state import runtime_state_service

    owner = SandboxOwner(
        settings.NEXENT_RUNTIME_DEPLOYMENT_ID, settings.NEXENT_RUNTIME_POD_NAMESPACE,
        settings.NEXENT_RUNTIME_POD_NAME, settings.NEXENT_RUNTIME_POD_UID,
        settings.NEXENT_RUNTIME_POD_IP, PROCESS_EPOCH,
    )
    return _coordinator(owner, settings.NEXENT_SANDBOX_WORKSPACE_MOUNT, settings.AGENT_WORKSPACE_ROOT,
                         runtime_state_service.client)


def run_options(request, tenant_id, *, kind='CHAT', cancel=lambda: None):
    coordinator = get_coordinator()
    if coordinator is None:
        return {}
    return {'tenant_id': tenant_id, 'execution_run_id': ensure_request_run_id(request), 'kind': kind, 'cancel': cancel}


def bind_request_reservation(request, user_id):
    coordinator = get_coordinator()
    if coordinator is None:
        return
    from management.services.agent.execution import _agent_run_identifier
    from management.services.agent.lifecycle import agent_run_manager

    lease = agent_run_manager.get_distributed_lease(_agent_run_identifier(request), user_id)
    if lease is None:
        raise RuntimeError('Kubernetes execution has no admitted conversation lease')
    request.__dict__['_runtime_distributed_lease'] = lease
    request.__dict__['_runtime_run_reference'] = coordinator.reference(lease)


def associate_request(request, **associations):
    coordinator = get_coordinator()
    if coordinator is None:
        return
    lease = request.__dict__.get('_runtime_distributed_lease')
    if lease is None:
        raise RuntimeError('Kubernetes business association has no admitted lease')
    coordinator.associate(lease, **associations)
    request.__dict__['_runtime_run_reference'] = coordinator.reference(lease)


def get_runtime_recovery():
    coordinator = get_coordinator()
    recovery = getattr(coordinator, 'recovery', None)
    if recovery is None:
        raise RuntimeError('Scoped Runtime recovery has not been initialized')
    return recovery


def require_business_admission():
    """Reject new work when running-state coordination is unavailable."""
    from fastapi import HTTPException
    from runtime.identity import uses_distributed_runtime

    if uses_distributed_runtime() and get_coordinator().lost_coordination.is_set():
        raise HTTPException(status_code=503, detail='Runtime is not accepting execution',
                            headers={'Retry-After': '1'})


def configure_runtime_coordination(manager, run_manager, state_service):
    """Call during lifespan startup before recovery or business admission."""
    from contracts.constants import environment as settings

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
    from management.db.runtime_recovery import fail_exact_owned_work
    from runtime.sandbox_owner import SandboxOwnerObserver
    from runtime.sandbox_recovery import SandboxRuntimeRecovery

    coordinator.recovery = SandboxRuntimeRecovery(
        coordinator, kubernetes_api,
        SandboxOwnerObserver(kubernetes_api, coordinator.owner, facts.read(coordinator.owner.epoch)['process']),
        fail_exact_owned_work, workspace_root=settings.AGENT_WORKSPACE_ROOT,
    )
    coordinator.recovery.recover(startup=True)
    coordinator.recovery.verify_current_owner_resources_absent(time.monotonic() + 10)
    coordinator.claim_owner()
    from runtime.api.application import app
    app.state.sandbox_coordinator = coordinator
    run_manager.configure_coordinator(coordinator)
    stream_state = SandboxStreamState(
        coordinator, run_ttl=settings.RUNTIME_RUN_TTL_SECONDS, completed_ttl=settings.RUNTIME_COMPLETED_TTL_SECONDS,
        stream_ttl=settings.RUNTIME_STREAM_TTL_SECONDS, cancel_ttl=settings.RUNTIME_CANCEL_TTL_SECONDS,
        max_stream_length=settings.RUNTIME_STREAM_MAX_LEN,
    )
    state_service.configure_distributed(stream_state)
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
    return service
