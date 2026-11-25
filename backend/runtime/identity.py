# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Internal execution IDs independent of conversation and durable business IDs."""

import asyncio
import logging
import re
import uuid
from typing import Any


_RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
PROCESS_EPOCH = uuid.uuid4().hex


def resolve_execution_run_id(run_id: str | None) -> str:
    if run_id is None:
        return uuid.uuid4().hex
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError("execution run_id must contain 32 lowercase hexadecimal characters")
    return run_id


def ensure_request_run_id(request: Any, *, new: bool = False) -> str:
    """A new admission gets one ID; recursive preparation reuses that ID."""
    if new:
        request.__dict__.pop('_runtime_distributed_lease', None)
        request.__dict__.pop('_runtime_run_reference', None)
        request.__dict__.pop('_runtime_execution_future', None)
    current = None if new else request.__dict__.get("_runtime_execution_run_id")
    run_id = resolve_execution_run_id(current)
    request.__dict__["_runtime_execution_run_id"] = run_id
    return run_id


# Server-owned references are carried explicitly through channels and callbacks.
def reference_options(source):
    reference = source.__dict__.get('_runtime_run_reference') if source is not None else None
    return {'run_ref': reference} if reference is not None else {}


def execution_conversation_id(request):
    reference = request.__dict__.get('_runtime_run_reference')
    return reference.conversation_id if reference is not None else request.conversation_id


def uses_distributed_runtime():
    from contracts.constants.environment import IS_DEPLOYED_BY_KUBERNETES, NEXENT_SANDBOX_PROVIDER

    return NEXENT_SANDBOX_PROVIDER == 'kubernetes' and bool(IS_DEPLOYED_BY_KUBERNETES)


def current_reference_options(tenant_id, user_id, conversation_id):
    if not uses_distributed_runtime():
        return {}
    if not tenant_id:
        raise ValueError('Distributed Runtime lookup requires a trusted tenant identity')
    from runtime.sandbox_runtime import get_coordinator

    return {'run_ref': get_coordinator().current_reference(tenant_id, user_id, conversation_id)}


async def reserve_runtime_run(manager, conversation_id, user_id, **options):
    if not options:
        return manager.reserve_agent_run(conversation_id, user_id)
    from nexent.core.concurrency import ManagedTaskSpec

    from runtime.thread_management import runtime_thread_manager

    execution = runtime_thread_manager.submit(
        'control-io', ManagedTaskSpec(task_name='reserve-distributed-run', owner='runtime'),
        manager.reserve_agent_run, conversation_id, user_id, **options,
    )
    pending = asyncio.wrap_future(execution.future)
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        def release_late(future):
            if future.cancelled() or future.exception() is not None:
                return
            try:
                manager.release_agent_run_reservation(conversation_id, user_id, future.result())
            except Exception:
                logging.getLogger(__name__).warning('Late distributed admission cleanup failed')

        execution.future.add_done_callback(release_late)
        pending.add_done_callback(lambda result: None if result.cancelled() else result.exception())
        raise


async def runtime_coordination_call(task_name, function, *args, **kwargs):
    if not uses_distributed_runtime():
        return function(*args, **kwargs)
    from nexent.core.concurrency import run_blocking

    return await run_blocking(task_name, function, *args, lane='control-io', owner='runtime', **kwargs)


async def runtime_journal_call(task_name, function, *args, **kwargs):
    """Settle the durable association before cancellation can release its reservation."""
    if not uses_distributed_runtime():
        return function(*args, **kwargs)

    task = asyncio.create_task(runtime_coordination_call(task_name, function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled() and (error := task.exception()) is not None:
            logging.getLogger(__name__).warning('Runtime journal write failed during cancellation: %s', type(error).__name__)
        raise
