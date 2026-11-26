# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Kubernetes Runtime protocol wiring; Docker keeps its existing local ownership."""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from redis.exceptions import RedisError

from runtime.identity import PROCESS_EPOCH, uses_distributed_runtime
from runtime.sandbox_coordination import SandboxRunBusy, SandboxRunCoordinator, SandboxRunLease
from runtime.sandbox_journal import SandboxCoordinationUnknown, SandboxRunJournal
from runtime.sandbox_owner import SandboxOwnerFacts, process_identity

from nexent.core.agents.sandbox_contracts import SandboxOwner
from nexent.core.concurrency import ManagedThreadSpec, run_blocking


@dataclass(frozen=True)
class OwnedSandboxRun:
    coordinator: SandboxRunCoordinator
    lease: SandboxRunLease

    def finish(self):
        try:
            self.coordinator.finish(self.lease)
        except Exception:
            self.coordinator.signal_lost()
            raise


def check_agentos_admission():
    coordinator = get_coordinator()
    if coordinator is not None and coordinator.lost_coordination.is_set():
        raise HTTPException(503, detail={"code": "AGENTOS_SANDBOX_OWNERSHIP_UNKNOWN"})


async def reserve_agentos_sandbox(tenant_id, user_id, conversation_id, run_id, *, kind, cancel):
    coordinator = get_coordinator()
    if coordinator is None:
        return None

    def reserve_and_activate():
        lease = coordinator.reserve(tenant_id, user_id, conversation_id, run_id, kind=kind, cancel=cancel)
        try:
            coordinator.activate(lease)
        except BaseException:
            coordinator.finish(lease)
            raise
        return OwnedSandboxRun(coordinator, lease)

    reservation = asyncio.create_task(run_blocking(
        "agentos-sandbox-reserve", reserve_and_activate, lane="control-io", owner="runtime",
    ))
    try:
        return await asyncio.shield(reservation)
    except asyncio.CancelledError:
        result, = await asyncio.gather(reservation, return_exceptions=True)
        if isinstance(result, OwnedSandboxRun):
            await release_agentos_sandbox(result)
        raise
    except SandboxRunBusy as exc:
        raise HTTPException(409, detail={"code": "AGENTOS_RUN_ALREADY_ACTIVE"}) from exc
    except (SandboxCoordinationUnknown, RedisError, OSError) as exc:
        raise HTTPException(503, detail={"code": "AGENTOS_SANDBOX_OWNERSHIP_UNKNOWN"}) from exc


async def release_agentos_sandbox(owned, worker=None):
    if owned is None:
        return
    if worker is not None and not worker.done():
        # Managed worker callbacks release only after execution really exits.
        worker.add_done_callback(lambda _: owned.finish())
        return
    await run_blocking("agentos-sandbox-release", owned.finish, lane="control-io", owner="runtime")


@lru_cache(maxsize=1)
def _coordinator(owner, root, workspace_root, redis_client):
    return SandboxRunCoordinator(redis_client, SandboxRunJournal(Path(root) / '.sandbox-control'), owner,
                                  lease_seconds=30, workspace_root=workspace_root)


def get_coordinator():
    from contracts.constants import environment as settings

    if not uses_distributed_runtime():
        return None
    from infrastructure.redis.run_state import runtime_state_service

    owner = SandboxOwner(
        settings.NEXENT_RUNTIME_DEPLOYMENT_ID, settings.NEXENT_RUNTIME_POD_NAMESPACE,
        settings.NEXENT_RUNTIME_POD_NAME, settings.NEXENT_RUNTIME_POD_UID,
        settings.NEXENT_RUNTIME_POD_IP, PROCESS_EPOCH,
    )
    return _coordinator(owner, settings.NEXENT_SANDBOX_WORKSPACE_MOUNT, settings.AGENT_WORKSPACE_ROOT,
                         runtime_state_service.client)


def configure_runtime_coordination(manager, state):
    """Call during lifespan startup before recovery or business admission."""
    from contracts.constants import environment as settings

    if not settings.NEXENT_SANDBOX_ENABLED:
        return None
    coordinator = get_coordinator()
    if coordinator is None:
        return None
    boot_time = datetime.now(timezone.utc)
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
    from infrastructure.rdb.agent_execution import RunIdentity, recover_stopped_execution
    from infrastructure.rdb.sandbox_recovery import fail_exact_owned_work
    from runtime.sandbox_owner import SandboxOwnerObserver
    from runtime.sandbox_recovery import SandboxRuntimeRecovery

    recover_business = settings.NEXENT_RECOVERY_MODE == 'startup'
    coordinator.recovery = SandboxRuntimeRecovery(
        coordinator, kubernetes_api,
        SandboxOwnerObserver(kubernetes_api, coordinator.owner, facts.read(coordinator.owner.epoch)['process']),
        fail_exact_owned_work if recover_business else None, workspace_root=settings.AGENT_WORKSPACE_ROOT,
        fail_execution=(lambda *identity: recover_stopped_execution(RunIdentity(*identity))) if recover_business else None,
    )
    coordinator.recovery.recover(startup=True)
    coordinator.recovery.verify_current_owner_resources_absent(time.monotonic() + 10)
    coordinator.claim_owner()
    if state is not None:
        state.sandbox_coordinator = coordinator
        state.sandbox_restart_cutoff = None
        if recover_business and coordinator.recovery.recover()["restart_confirmed"]:
            # A repeated scan must never move the scheduler cutoff forward.
            state.sandbox_restart_cutoff = boot_time

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
