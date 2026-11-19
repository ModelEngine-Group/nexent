# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-QUOTA-READ-02 keep bounded current-actor metadata work."""

import asyncio
from time import monotonic

import pytest
from management.services.knowledge_base import quota_read as module
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal


async def test_real_actor_resource_tenant_and_owned_context(mocker):
    actor = ServicePrincipal("reader", "actual-tenant")
    captured = []

    async def blocking(name, action, *args, **kwargs):
        assert args == ("target-tenant", actor)
        assert (
            kwargs["lane"] == "control-io"
            and kwargs["owner"] == "management.knowledge_base"
        )
        captured.append(kwargs["context"])
        return {"hard_limit_bytes": 7}

    work = mocker.patch.object(module, "run_blocking", side_effect=blocking)
    assert await module.read_tenant_quota("target-tenant", actor) == {
        "hard_limit_bytes": 7
    }
    assert work.await_count == 1 and captured[0].cancelled.is_set()


async def test_timeout_logs_once_and_cancels_without_empty_success(mocker, caplog):
    contexts = []

    async def blocking(*args, **kwargs):
        contexts.append(kwargs["context"])
        await asyncio.sleep(1)

    mocker.patch.object(module, "run_blocking", side_effect=blocking)
    mocker.patch.object(
        module,
        "OperationContext",
        side_effect=lambda operation_id, deadline, **kw: OperationContext(
            operation_id, monotonic() + 0.03, **kw
        ),
    )
    with pytest.raises(DeadlineExceeded):
        await module.read_tenant_quota("sensitive-tenant", ServicePrincipal("u", "t"))
    assert contexts[0].cancelled.is_set()
    records = [r for r in caplog.records if "tenant_quota_read_timeout" in r.message]
    assert len(records) == 1 and records[0].levelname == "WARNING"
    assert "sensitive-tenant" not in caplog.text and "phase=metadata" in caplog.text


async def test_refused_reader_is_not_retried_or_converted_to_empty_quota(mocker):
    work = mocker.patch.object(module, "run_blocking", side_effect=ScopeDenied())
    with pytest.raises(ScopeDenied):
        await module.read_tenant_quota("tenant", ServicePrincipal("u", "t"))
    assert work.await_count == 1


async def test_real_managed_read_exits_after_deadline(mocker, caplog):
    from threading import Event
    from time import sleep
    from types import SimpleNamespace

    from nexent.core.concurrency import (
        LanePolicy,
        ThreadManager,
        clear_default_thread_manager,
        set_default_thread_manager,
    )

    started, closed = Event(), Event()
    contexts = []

    def read(*args, context):
        contexts.append(context)
        started.set()
        try:
            while not context.cancelled.is_set():
                context.remaining()
                sleep(0.002)
        finally:
            closed.set()

    mocker.patch.object(
        module, "TenantQuotaReader", return_value=SimpleNamespace(read=read)
    )
    mocker.patch.object(
        module,
        "OperationContext",
        side_effect=lambda operation_id, deadline, **kw: OperationContext(
            operation_id, monotonic() + 0.2, **kw
        ),
    )
    manager = ThreadManager(
        service_name="quota-read-deadline",
        lane_policies={"control-io": LanePolicy("control-io", 1, 1)},
    )
    manager.start()
    set_default_thread_manager(manager)
    try:
        with pytest.raises(DeadlineExceeded):
            await module.read_tenant_quota("target", ServicePrincipal("u", "t"))
        assert started.is_set() and contexts[0].cancelled.is_set()
    finally:
        result = await manager.shutdown(timeout=3)
        clear_default_thread_manager(manager)
    assert closed.is_set() and not result.stuck_execution_ids
    assert sum("tenant_quota_read_timeout" in r.message for r in caplog.records) == 1
