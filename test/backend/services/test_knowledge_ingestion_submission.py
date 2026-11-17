# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public submission preserves result shapes and never rewrites admitted or uncertain files."""

import asyncio
from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.errors.codes import ErrorCode
from management.services.knowledge_base.ingestion import submit_knowledge_files
from nexent.storage.errors import NotFound, OutcomeUnknown, ScopeDenied
from nexent.storage.models import OperationContext


@pytest.fixture
def submission(monkeypatch):
    from management.services.knowledge_base import ingestion as module

    actor = SimpleNamespace(user_id="user-a", tenant_id="tenant-a")
    records = Mock()
    closed, contexts = [], []

    @contextmanager
    def ports(tenant_id, user_id, *, context, include_files):
        assert (tenant_id, user_id, include_files) == ("tenant-a", "user-a", True)
        contexts.append(context)
        try:
            yield records
        finally:
            closed.append(True)

    async def blocking(name, fn, *args, lane, owner, **kwargs):
        assert lane == "control-io" and owner == "management.knowledge_base"
        return fn(*args, **kwargs)

    monkeypatch.setattr(module, "knowledge_resource_ports", ports)
    monkeypatch.setattr(module, "run_blocking", blocking)
    selector = Mock(
        side_effect=lambda records, actor, index_name, details, **kwargs: {
            "file_id": details["file_id"],
            "original_filename": "source.txt",
        }
    )
    monkeypatch.setattr(module, "resolve_ingestion_file", selector)
    coordinator = SimpleNamespace(
        accept=AsyncMock(
            side_effect=lambda file_id, *args, **kwargs: {
                "file_id": file_id,
                "process_task_id": file_id,
                "status": "UPLOADED",
            }
        )
    )
    files = [
        {
            "file_id": c * 32,
            "path_or_url": "knowledge_base/" + c,
            "filename": c + ".txt",
        }
        for c in ("b", "c")
    ]
    return SimpleNamespace(**locals())


async def test_local_staging_is_bound_before_admission_without_replacing_explicit_id(
    submission, monkeypatch
):
    s = submission
    s.selector.side_effect = NotFound()
    prepare = Mock(return_value={"stage_id": "a" * 32})
    publish = AsyncMock(
        return_value={"file_id": "c" * 32, "original_filename": "source.txt"}
    )
    monkeypatch.setattr(s.module, "prepare_staged_binding", prepare)
    monkeypatch.setattr(s.module, "publish_staged_binding", publish)
    result = await submit_knowledge_files(
        [{"path_or_url": "/owned/source.txt"}],
        "kb-one",
        s.actor,
        destination="local",
        coordinator=s.coordinator,
    )
    assert result == {"task_id": "c" * 32} and publish.await_count == 1
    assert s.coordinator.accept.await_args.args == ("c" * 32, s.actor)
    assert s.closed == [True]
    result = await submit_knowledge_files(
        s.files[:1], "kb-one", s.actor, destination="local", coordinator=s.coordinator
    )
    assert (
        result["failed_count"] == 1
        and prepare.call_count == 1
        and publish.await_count == 1
    )


async def test_single_file_returns_opaque_task_id_and_original_actor(submission):
    s = submission
    result = await submit_knowledge_files(
        s.files[:1], "kb-one", s.actor, coordinator=s.coordinator
    )
    assert result == {"task_id": "b" * 32}
    assert s.coordinator.accept.call_args.args == ("b" * 32, s.actor)
    assert s.coordinator.accept.call_args.kwargs["chunking_strategy"] == "basic"
    assert s.closed == [True]


async def test_local_binding_timeout_signals_cancellation_without_admitting(
    submission, monkeypatch
):
    s = submission
    s.selector.side_effect = NotFound()
    monkeypatch.setattr(
        s.module, "prepare_staged_binding", Mock(return_value={"stage_id": "a" * 32})
    )

    async def stalled(*args):
        await asyncio.sleep(10)

    publish = AsyncMock(side_effect=stalled)
    monkeypatch.setattr(s.module, "publish_staged_binding", publish)
    context = OperationContext("binding-timeout", monotonic() + 1)
    result = await submit_knowledge_files(
        [{"path_or_url": "/owned/staged.txt"}],
        "kb-one",
        s.actor,
        destination="local",
        coordinator=s.coordinator,
        context=context,
    )
    assert result["results"][0]["error_code"] == ErrorCode.SYSTEM_TIMEOUT.value
    assert publish.await_count == 1 and not s.coordinator.accept.called
    assert s.contexts[-1].cancelled.is_set()


async def test_empty_submission_does_not_open_ports_or_start_accept(submission):
    s = submission
    assert (
        await submit_knowledge_files([], "kb-one", s.actor, coordinator=s.coordinator)
        is None
    )
    s.selector.assert_not_called()
    s.coordinator.accept.assert_not_awaited()


async def test_batch_partial_failure_preserves_success_and_result_fields(submission):
    s = submission
    s.coordinator.accept.side_effect = [{"process_task_id": "b" * 32}, ScopeDenied()]
    result = await submit_knowledge_files(
        s.files, "kb-one", s.actor, coordinator=s.coordinator
    )
    assert result["status"] == "partial_success" and result["task_ids"] == ["b" * 32]
    assert result["submitted_count"] == 1 and result["failed_count"] == 1
    assert [row["status"] for row in result["results"]] == ["SUBMITTED", "FAILED"]
    assert result["results"][1]["error_code"] == ErrorCode.COMMON_FORBIDDEN.value
    assert s.coordinator.accept.await_count == 2 and len(s.closed) == 2
    s.records.patch.assert_not_called()


async def test_unknown_admission_does_not_replay_or_rewrite_the_file(submission):
    s = submission
    s.coordinator.accept.side_effect = OutcomeUnknown()
    result = await submit_knowledge_files(
        s.files[:1], "kb-one", s.actor, coordinator=s.coordinator
    )
    assert result["submitted_count"] == 0 and result["status"] == "failed"
    assert result["results"][0]["error_code"] == "KNOWLEDGE_OUTCOME_UNKNOWN"
    s.coordinator.accept.assert_awaited_once()
    s.records.patch.assert_not_called()


async def test_batch_deadline_closes_context_and_does_not_start_remaining_files(
    submission,
):
    s = submission
    finished = asyncio.Event()
    cancellation = []

    async def stalled(file_id, actor, *, context, **kwargs):
        cancellation.append(context.cancelled)
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    s.coordinator.accept.side_effect = stalled
    result = await submit_knowledge_files(
        s.files,
        "kb-one",
        s.actor,
        coordinator=s.coordinator,
        context=OperationContext("short-batch", monotonic() + 0.05),
    )
    assert result["failed_count"] == 2 and finished.is_set()
    assert all(
        row["error_code"] == ErrorCode.SYSTEM_TIMEOUT.value for row in result["results"]
    )
    s.coordinator.accept.assert_awaited_once()
    assert len(s.closed) == 1 and cancellation[0].is_set()


async def test_request_cancellation_signals_context_without_restarting_accept(
    submission,
):
    s = submission
    started = asyncio.Event()
    received = []

    async def stalled(file_id, actor, *, context, **kwargs):
        received.append(context)
        started.set()
        await asyncio.Event().wait()

    s.coordinator.accept.side_effect = stalled
    task = asyncio.create_task(
        submit_knowledge_files(s.files, "kb-one", s.actor, coordinator=s.coordinator)
    )
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert received[0].cancelled.is_set()
    s.coordinator.accept.assert_awaited_once()
