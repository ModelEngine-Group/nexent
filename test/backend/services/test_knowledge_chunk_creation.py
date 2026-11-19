# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime creation retains real SI admissions across isolated model and vector boundaries."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos import ModelResult
from contracts.agentos_knowledge import KnowledgeFileDelete
from contracts.knowledge_chunk_mutation import ChunkMutationIntent
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    run_blocking,
    set_default_thread_manager,
)
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    Revision,
    StorageScope,
    VectorKey,
    VectorRecord,
    WriteReceipt,
)
from runtime.knowledge_base.chunk_creation import ChunkCreationExecutor

from test.backend.services.test_knowledge_chunk_fencing import (
    context,
    publish,
)
from test.backend.services.test_knowledge_chunk_fencing import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_ingestion_coordinator import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)


@pytest.fixture
async def creation(sqlite_threads, lifecycle):
    s = lifecycle
    manager = ThreadManager(
        service_name="create-ut",
        lane_policies={
            "control-io": LanePolicy(
                "control-io",
                1,
                8,
                queue_timeout_seconds=1,
                cancel_grace_seconds=1,
                shutdown_grace_seconds=2,
            ),
        },
    )
    manager.start()
    set_default_thread_manager(manager)
    models = SimpleNamespace(
        embedding_dimensions=AsyncMock(return_value=3),
        invoke=AsyncMock(
            return_value=ModelResult(revision="r1", output=[[1.0, 0.0, 0.0]])
        ),
    )
    vectors = Mock()
    vectors.scope = StorageScope(
        "runtime", s.actor.tenant_id, s.actor.user_id, {"collection"}
    )
    stored = [None]
    vectors.get.side_effect = lambda *args, **kwargs: stored[0]

    def put(record, **kwargs):
        stored[0] = record
        return WriteReceipt("put", True)

    vectors.put.side_effect = put
    counters = {"open": 0, "close": 0}
    dimensions = []

    @contextmanager
    def ports(actor, collection, size, *, context):
        assert actor == s.actor and collection == "collection"
        dimensions.append(size)
        counters["open"] += 1
        try:
            yield vectors
        finally:
            counters["close"] += 1

    async def db(action, *args, **kwargs):
        return await run_blocking(
            "creation-ut-db", action, *args, lane="control-io", owner="unit", **kwargs
        )

    service = ChunkCreationExecutor(
        s.mutation, models, s.actor, "collection", ports=ports
    )
    value = ChunkMutationIntent(
        knowledge_id=1,
        chunk_id="manual",
        request_key="create",
        operation="create",
        resource_revision="a" * 64,
        changes={"content": "body", "filename": None, "location": {"title": "title"}},
    )
    try:
        yield SimpleNamespace(**locals())
    finally:
        clear_default_thread_manager(manager)
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids
        assert counters["open"] == counters["close"]


@pytest.mark.asyncio
async def test_no_model_creates_plaintext_without_fake_file_or_vector(creation):
    s = creation
    row = await s.service.execute(s.value, context=context())
    record = s.stored[0]
    assert row["status"] == "completed" and row["count_delta"] == 1
    assert (
        record.vector == ()
        and record.payload["file_id"] is None
        and record.payload["filename"] is None
    )
    assert record.generation == Revision(row["mutation_id"])
    assert await s.db(s.s.mutation.standalone_count, context=context()) == 1
    s.models.invoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('stored', ['body', ['after', 'merge'], 123])
async def test_create_invokes_standard_model_with_actual_actor_and_original_embedding_input(
    creation, stored,
):
    s = creation
    value = s.value.model_copy(
        update={
            "changes": {
                **s.value.changes,
                "content": stored,
                "embedding_input": "before metadata merge",
                "embedding_model": {"model_id": 2, "revision": "r1"},
            }
        }
    )
    row = await s.service.execute(value, context=context())
    call = s.models.invoke.await_args
    assert call.args[0].operation == "embedding" and call.args[0].input == [
        "before metadata merge"
    ]
    assert call.args[0].expected_revision == "r1" and call.args[1] == s.s.actor
    assert (
        s.stored[0].vector == (1.0, 0.0, 0.0)
        and s.stored[0].payload["embedding_model_id"] == 2
    )
    assert s.stored[0].payload['content'] == stored
    assert s.dimensions == [None, 3] and row["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("unavailable"),
        ModelResult(revision="r1", output=[]),
        ModelResult(revision="r1", output=[[]]),
    ],
)
async def test_existing_model_failure_semantics_save_plaintext_without_alternate_model(
    creation, failure
):
    s = creation
    if isinstance(failure, Exception):
        s.models.invoke.side_effect = failure
    else:
        s.models.invoke.return_value = failure
    value = s.value.model_copy(
        update={
            "changes": {
                **s.value.changes,
                "embedding_model": {"model_id": 2, "revision": "r1"},
            }
        }
    )
    assert (await s.service.execute(value, context=context()))["status"] == "completed"
    assert (
        s.stored[0].vector == () and s.stored[0].payload["embedding_model_id"] is None
    )
    assert s.models.invoke.await_count == 1


@pytest.mark.asyncio
async def test_explicit_existing_id_is_conditionally_replaced_and_not_counted_twice(
    creation,
):
    s = creation
    s.stored[0] = VectorRecord(
        VectorKey("collection", "manual"),
        (),
        {"knowledge_id": 1, "file_id": None, "file_version": None, "chunk_index": None},
        Revision("previous"),
    )
    row = await s.service.execute(s.value, context=context())
    assert row["count_delta"] == 0
    assert s.vectors.put.call_args.kwargs["expected_generation"] == Revision("previous")
    assert (await s.service.execute(s.value, context=context()))["mutation_id"] == row[
        "mutation_id"
    ]
    assert s.vectors.put.call_count == 1


@pytest.mark.asyncio
async def test_file_bound_create_preserves_real_generation_and_file_delta(creation):
    s = creation
    handle = await s.db(publish, s.s)
    value = s.value.model_copy(
        update={
            "file_ref": {
                "knowledge_id": 1,
                "file_id": handle["file_id"],
                "file_version": 1,
            },
            "generation": handle["attempt_id"],
            "chunk_index": 3,
        }
    )
    row = await s.service.execute(value, context=context())
    assert row["file_id"] == handle["file_id"] and s.stored[0].generation == Revision(
        handle["attempt_id"]
    )
    assert (
        await s.db(
            s.s.mutation.file_delta,
            s.value.model_validate(value.model_dump()).file_ref,
            handle["attempt_id"],
            context=context(),
        )
        == 1
    )


@pytest.mark.asyncio
async def test_missing_file_binding_cannot_replace_an_existing_file_chunk(creation):
    s = creation
    s.stored[0] = VectorRecord(
        VectorKey("collection", "manual"),
        (),
        {"knowledge_id": 1, "file_id": "a" * 32, "file_version": 1, "chunk_index": 1},
        Revision("published"),
    )
    with pytest.raises(ScopeDenied):
        await s.service.execute(s.value, context=context())
    s.vectors.put.assert_not_called()
    await s.db(s.s.mutation.assert_drained, context=context())


@pytest.mark.asyncio
async def test_unknown_put_remains_uncounted_and_duplicate_never_reinvokes_or_rewrites(
    creation,
):
    s = creation
    s.vectors.put.side_effect = OutcomeUnknown()
    with pytest.raises(OutcomeUnknown):
        await s.service.execute(s.value, context=context())
    assert (await s.service.execute(s.value, context=context()))["status"] == "unknown"
    assert s.vectors.put.call_count == 1
    with pytest.raises(Conflict):
        await s.db(s.s.mutation.assert_drained, context=context())


@pytest.mark.asyncio
async def test_ledger_ack_failure_after_put_does_not_rewrite(creation, monkeypatch):
    s = creation
    monkeypatch.setattr(s.s.mutation, "complete", Mock(side_effect=OutcomeUnknown()))
    with pytest.raises(OutcomeUnknown):
        await s.service.execute(s.value, context=context())
    assert (await s.service.execute(s.value, context=context()))["status"] == "writing"
    assert s.vectors.put.call_count == 1


@pytest.mark.asyncio
async def test_model_budget_exhaustion_does_not_open_a_new_write_budget(creation):
    import asyncio
    from time import monotonic

    from nexent.storage.models import OperationContext

    s = creation
    budget = OperationContext("short-model", monotonic() + 0.05)

    async def expire(*args):
        await asyncio.sleep(0.15)
        raise RuntimeError("model failure")

    s.models.invoke.side_effect = expire
    value = s.value.model_copy(
        update={
            "changes": {
                **s.value.changes,
                "embedding_model": {"model_id": 2, "revision": "r1"},
            }
        }
    )
    with pytest.raises(DeadlineExceeded):
        await s.service.execute(value, context=budget)
    s.vectors.put.assert_not_called()


@pytest.mark.asyncio
async def test_file_deleted_during_model_call_is_revalidated_before_put(creation):
    s = creation
    handle = await s.db(publish, s.s)
    value = s.value.model_copy(
        update={
            "file_ref": {
                "knowledge_id": 1,
                "file_id": handle["file_id"],
                "file_version": 1,
            },
            "generation": handle["attempt_id"],
            "chunk_index": 3,
            "changes": {
                **s.value.changes,
                "embedding_model": {"model_id": 2, "revision": "r1"},
            },
        }
    )

    async def deleting(*args):
        await s.db(
            s.s.policy.submit,
            KnowledgeFileDelete(
                knowledge_id=1,
                file_id=handle["file_id"],
                file_version=1,
                idempotency_key="delete",
            ),
            context=context(),
        )
        return ModelResult(revision="r1", output=[[1.0, 0.0, 0.0]])

    s.models.invoke.side_effect = deleting
    with pytest.raises(Conflict):
        await s.service.execute(value, context=context())
    s.vectors.put.assert_not_called()
    await s.db(s.s.mutation.assert_drained, context=context())


@pytest.mark.asyncio
async def test_cancelled_model_never_starts_the_writer_or_mutates_parent_cancellation(
    creation,
):
    import asyncio
    from dataclasses import replace
    from threading import Event

    s = creation
    started = asyncio.Event()
    parent = Event()
    budget = replace(context(), cancelled=parent)

    async def blocked(*args):
        started.set()
        await asyncio.Event().wait()

    s.models.invoke.side_effect = blocked
    value = s.value.model_copy(
        update={
            "changes": {
                **s.value.changes,
                "embedding_model": {"model_id": 2, "revision": "r1"},
            }
        }
    )
    task = asyncio.create_task(s.service.execute(value, context=budget))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    s.vectors.put.assert_not_called()
    assert not parent.is_set()
    with pytest.raises(Conflict):
        await s.db(s.s.mutation.assert_drained, context=context())


@pytest.mark.asyncio
async def test_foreign_actor_port_does_not_reach_model_or_vector(creation):
    s = creation
    s.vectors.scope = StorageScope(
        "runtime", s.s.actor.tenant_id, "other-user", {"collection"}
    )
    with pytest.raises(ScopeDenied):
        await s.service.execute(s.value, context=context())
    s.models.invoke.assert_not_awaited()
    s.vectors.put.assert_not_called()
    await s.db(s.s.mutation.assert_drained, context=context())


@pytest.mark.asyncio
async def test_normalized_create_does_not_add_a_filename_length_limit(creation):
    s = creation
    value = s.value.model_copy(
        update={"changes": {**s.value.changes, "filename": "x" * 4096}}
    )
    assert (await s.service.execute(value, context=context()))["status"] == "completed"
    assert s.stored[0].payload["filename"] == "x" * 4096
