# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deletion publishes only physical absence from one authorized fenced attempt."""

import asyncio
from contextlib import contextmanager
from threading import Event
from time import monotonic

import pytest
from contracts.agentos_knowledge import KnowledgeFileDelete, KnowledgeJobLookup
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    NotFound,
    OutcomeUnknown,
    PartialFailure,
    ScopeDenied,
)
from nexent.storage.models import DeleteReceipt, OperationContext, WriteOutcome
from runtime.knowledge_base.deletion import KnowledgeDeleteWorker

from infrastructure.rdb.knowledge_jobs import JOBS
from test.backend.services.test_knowledge_worker import (
    setup as setup,  # noqa: PLC0414 - Actual scoped jobs and managed I/O fixture.
)


@pytest.fixture
async def deletion(setup):
    s = setup
    request = KnowledgeFileDelete(
        knowledge_id=1, file_id=s.request.file_id, file_version=0, idempotency_key="delete",
    )
    state = await s.db(s.policy.submit, request, context=s.context)
    lookup = KnowledgeJobLookup(**state.model_dump(include={"knowledge_id", "file_id", "file_version", "job_id"}))
    grant = s.grant.model_copy(update={"action": "delete", "artifact": None, "parser_version": None})
    s.client.authorize_knowledge.return_value = grant
    s.vectors.count.side_effect = [1, 0]
    s.vectors.delete.return_value = (DeleteReceipt("removed", True),)

    @contextmanager
    def ports(actor, value, *, context):
        assert actor == s.actor and value.model_copy(update={"legacy_sources": []}) == grant
        try:
            yield s.vectors
        finally:
            s.closed.append(True)

    worker = KnowledgeDeleteWorker(s.client, jobs=s.job_ports, ports=ports)
    return s, request, state, lookup, worker


async def test_delete_confirms_absence_and_duplicate_never_calls_storage(deletion):
    s, _, state, lookup, worker = deletion
    final = await worker.process(lookup, s.actor, owner_id="owner", context=s.context)
    assert final.status == "deleted" and final.physical_cleanup_complete
    assert final.processed_chunks == final.total_chunks == 1
    row = await s.db(s.records.get, JOBS, state.job_id, context=s.context)
    assert row["write_started"] and row["writer_ended"] and not row["reconcile_required"]
    assert row["owner_id"] == "owner" and row["attempt_id"]
    assert s.closed == [True]
    where = s.vectors.delete.call_args.args[1]
    assert [(p.field, p.operator, p.value) for p in where.terms] == [
        ("knowledge_id", "eq", 1), ("file_id", "eq", lookup.file_id), ("file_version", "lte", 0),
    ]
    assert await worker.process(lookup, s.actor, owner_id="other", context=s.context) == final
    s.vectors.delete.assert_called_once()
    assert s.vectors.count.call_count == 2
    s.models.invoke.assert_not_awaited()
    assert all(c.args[0].action == "delete" for c in s.client.authorize_knowledge.call_args_list)


@pytest.mark.parametrize("result", [0, NotFound()])
async def test_explicit_empty_or_absent_collection_needs_no_delete(deletion, result):
    s, _, _, lookup, worker = deletion
    s.vectors.count.side_effect = result if isinstance(result, Exception) else None
    s.vectors.count.return_value = result
    final = await worker.process(lookup, s.actor, owner_id="owner", context=s.context)
    assert final.status == 'deleted' and final.processed_chunks == final.total_chunks == 0
    s.vectors.delete.assert_not_called()


@pytest.mark.parametrize("failure", [
    OutcomeUnknown(), PartialFailure(results=(DeleteReceipt("one", False, WriteOutcome.UNKNOWN),)),
])
async def test_uncertain_delete_stays_pending_and_never_replays(deletion, failure):
    s, _, state, lookup, worker = deletion
    s.vectors.delete.side_effect = failure
    with pytest.raises(type(failure)):
        await worker.process(lookup, s.actor, owner_id="owner", context=s.context)
    row = await s.db(s.records.get, JOBS, state.job_id, context=s.context)
    assert row["status"] == "cleanup_pending" and row["reconcile_required"]
    assert not row["physical_cleanup_complete"]
    await worker.process(lookup, s.actor, owner_id="another", context=s.context)
    s.vectors.delete.assert_called_once()


async def test_nonzero_after_one_delete_is_not_complete_or_retried(deletion):
    s, _, _, lookup, worker = deletion
    s.vectors.count.side_effect = [1, 1]
    with pytest.raises(Conflict):
        await worker.process(lookup, s.actor, owner_id="owner", context=s.context)
    assert (await s.db(s.policy.inspect, lookup, context=s.context)).status == "cleanup_pending"
    s.vectors.delete.assert_called_once()


async def test_file_cleanup_confirms_native_and_managed_counts_before_terminal_state(deletion, mocker):
    s, _, _, lookup, worker = deletion
    generations = {"a" * 32: 0}
    mocker.patch.object(s.policy, "native_cleanup_generations", return_value=generations)
    worker.native_cleanup = mocker.Mock(return_value=2)
    final = await worker.process(lookup, s.actor, owner_id="owner", context=s.context)
    assert final.status == "deleted" and final.processed_chunks == 3
    actor, grant, supplied = worker.native_cleanup.call_args.args
    assert actor == s.actor and grant.file_id == lookup.file_id and supplied == generations


async def test_uncertain_native_cleanup_is_not_replayed_or_published(deletion, mocker):
    s, _, _, lookup, worker = deletion
    mocker.patch.object(s.policy, "native_cleanup_generations", return_value={"a" * 32: 0})
    worker.native_cleanup = mocker.Mock(side_effect=OutcomeUnknown())
    with pytest.raises(OutcomeUnknown):
        await worker.process(lookup, s.actor, owner_id="owner", context=s.context)
    state = await worker.process(lookup, s.actor, owner_id="other", context=s.context)
    assert state.status == "cleanup_pending" and state.reconcile_required
    assert not state.physical_cleanup_complete
    worker.native_cleanup.assert_called_once()


async def test_legacy_grant_triggers_cleanup_without_any_runtime_upload_generation(deletion, mocker):
    s, _, _, lookup, worker = deletion
    grant = s.client.authorize_knowledge.return_value.model_copy(update={"legacy_sources": ["files/legacy.txt"]})
    s.client.authorize_knowledge.return_value = grant
    s.vectors.count.side_effect = None
    s.vectors.count.return_value = 0
    worker.native_cleanup = mocker.Mock(return_value=3)
    state = await worker.process(lookup, s.actor, owner_id="owner", context=s.context)
    assert state.status == "deleted" and state.processed_chunks == 3
    assert worker.native_cleanup.call_args.args == (s.actor, grant, {})
    s.vectors.delete.assert_not_called()


async def test_total_deadline_cancels_authorization_without_storage_or_retry(deletion, caplog):
    s, _, _, lookup, worker = deletion
    cancelled = []

    async def hanging(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    s.client.authorize_knowledge.side_effect = hanging
    with pytest.raises(DeadlineExceeded):
        await worker.process(lookup, s.actor, owner_id="owner",
                             context=OperationContext("timeout", monotonic() + 0.05))
    assert cancelled == [True]
    s.client.authorize_knowledge.assert_awaited_once()
    s.vectors.delete.assert_not_called()
    s.vectors.count.assert_not_called()
    assert "knowledge_delete_timeout" in caplog.text
    assert not any(r.levelname == "ERROR" for r in caplog.records)


async def test_revocation_after_delete_does_not_publish_completion(deletion):
    s, _, _, lookup, worker = deletion
    s.client.authorize_knowledge.side_effect = [s.client.authorize_knowledge.return_value, ScopeDenied()]
    with pytest.raises(ScopeDenied):
        await worker.process(lookup, s.actor, owner_id="owner", context=s.context)
    assert (await s.db(s.policy.inspect, lookup, context=s.context)).status == "cleanup_pending"
    assert s.closed == [True]


async def test_cancelled_before_finalize_never_completes_later(deletion, mocker):
    s, _, _, lookup, worker = deletion
    original = s.policy.finish_delete
    entered, release, ended = asyncio.Event(), Event(), Event()
    loop = asyncio.get_running_loop()

    def delayed(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(2)
            kwargs["context"].remaining()
            return original(*args, **kwargs)
        finally:
            ended.set()

    mocker.patch.object(s.policy, "finish_delete", delayed)
    task = asyncio.create_task(worker.process(lookup, s.actor, owner_id="owner", context=s.context))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    await s.db(lambda: ended.wait(1))
    assert (await s.db(s.policy.inspect, lookup, context=s.context)).status == "cleanup_pending"
