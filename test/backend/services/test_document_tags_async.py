# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOCUMENT-TAGS-02 bound optional display without retries or leaking work."""

import asyncio
from time import monotonic

import pytest
from management.services.tag import document_projection as module
from nexent.storage.errors import Unavailable
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal


async def test_async_success_owns_actual_identity_lane_and_context(mocker):
    captured = []
    actor = ServicePrincipal("reader", "tenant-a")
    files = [{"path_or_url": "a"}]

    async def blocking(name, callback, *args, **kwargs):
        assert args == (files, "kb", actor)
        assert (name, kwargs["lane"], kwargs["owner"]) == (
            "document-tag-projection",
            "control-io",
            "management.tag",
        )
        captured.append(kwargs["context"])
        return [dict(files[0], tags=[{"display_value": "First"}])]

    work = mocker.patch.object(module, "run_blocking", side_effect=blocking)
    result = await module.project_authorized_document_tags(
        files, index_name="kb", actor=actor
    )
    assert result[0]["tags"] == [{"display_value": "First"}]
    assert work.await_count == 1 and captured[0].cancelled.is_set()


async def test_total_deadline_returns_original_empty_tags_cancels_once_and_redacts(
    mocker, caplog
):
    captured, exited = [], []

    async def blocking(*args, **kwargs):
        captured.append(kwargs["context"])
        try:
            await asyncio.sleep(1)
        finally:
            exited.append(True)

    mocker.patch.object(module, "run_blocking", side_effect=blocking)
    mocker.patch.object(
        module,
        "OperationContext",
        side_effect=lambda operation_id, deadline, **kw: OperationContext(
            operation_id, monotonic() + 0.03, **kw
        ),
    )
    files = [{"path_or_url": "sensitive-document-key", "chunk_count": 4}]
    assert await module.project_authorized_document_tags(
        files, index_name="kb", actor=ServicePrincipal("u", "t")
    ) == [dict(files[0], tags=[])]
    assert captured[0].cancelled.is_set() and exited == [True]
    records = [
        r for r in caplog.records if "document_tag_projection_timeout" in r.message
    ]
    assert len(records) == 1 and records[0].levelname == "WARNING"
    assert (
        "phase=display" in caplog.text and "sensitive-document-key" not in caplog.text
    )
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


async def test_client_cancellation_propagates_and_signals_owned_scope(mocker):
    captured = []

    async def blocking(*args, **kwargs):
        captured.append(kwargs["context"])
        raise asyncio.CancelledError()

    mocker.patch.object(module, "run_blocking", side_effect=blocking)
    with pytest.raises(asyncio.CancelledError):
        await module.project_authorized_document_tags(
            [{"path_or_url": "a"}], index_name="kb", actor=ServicePrincipal("u", "t")
        )
    assert captured[0].cancelled.is_set()


async def test_admission_failure_preserves_optional_display_without_retry(
    mocker, caplog
):
    work = mocker.patch.object(module, "run_blocking", side_effect=Unavailable())
    assert await module.project_authorized_document_tags(
        [{"file": "one"}], index_name="kb", actor=ServicePrincipal("u", "t")
    ) == [{"file": "one", "tags": []}]
    assert work.await_count == 1
    assert (
        sum("document_tag_projection_unavailable" in r.message for r in caplog.records)
        == 1
    )


async def test_real_managed_worker_exits_after_display_deadline(mocker, caplog):
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

    def project(*args, context):
        contexts.append(context)
        started.set()
        try:
            while not context.cancelled.is_set():
                context.remaining()
                sleep(0.002)
        finally:
            closed.set()

    mocker.patch.object(
        module, "DocumentTagProjection", return_value=SimpleNamespace(project=project)
    )
    mocker.patch.object(
        module,
        "OperationContext",
        side_effect=lambda operation_id, deadline, **kw: OperationContext(
            operation_id, monotonic() + 0.2, **kw
        ),
    )
    manager = ThreadManager(
        service_name="document-tags-timeout",
        lane_policies={"control-io": LanePolicy("control-io", 1, 1)},
    )
    manager.start()
    set_default_thread_manager(manager)
    try:
        result = await module.project_authorized_document_tags(
            [{"path_or_url": "a"}], index_name="kb", actor=ServicePrincipal("u", "t")
        )
        assert (
            result == [{"path_or_url": "a", "tags": []}]
            and started.is_set()
            and contexts[0].cancelled.is_set()
        )
    finally:
        report = await manager.shutdown(timeout=3)
        clear_default_thread_manager(manager)
    assert not report.stuck_execution_ids and closed.is_set()
    assert (
        sum("document_tag_projection_timeout" in r.message for r in caplog.records) == 1
    )
