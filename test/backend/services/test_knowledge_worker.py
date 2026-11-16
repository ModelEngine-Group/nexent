# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime upload worker composes actual job and ingestion policies over controlled I/O."""

import asyncio
import hashlib
import io
from contextlib import contextmanager
from threading import Event
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from contracts.agentos import ModelResult
from contracts.agentos_knowledge import (
    CleanseArtifact,
    CleanseBlock,
    KnowledgeFileDelete,
    KnowledgeFileGrant,
    KnowledgeFileUpload,
    KnowledgeJobLookup,
    ObjectReference,
)
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    run_blocking,
    set_default_thread_manager,
)
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OperationCancelled,
    OutcomeUnknown,
)
from nexent.storage.models import (
    FieldPatch,
    ObjectMetadata,
    ObjectRef,
    OperationContext,
    Revision,
    StorageScope,
    VectorCollectionInfo,
    WriteReceipt,
)
from runtime.knowledge_base.jobs import KnowledgeJobs
from runtime.knowledge_base.worker import KnowledgeUploadWorker

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.knowledge_jobs import (
    FILES,
    JOBS,
    bind_knowledge_jobs,
    files,
    jobs,
)


@pytest.fixture
async def setup(mocker):
    manager = ThreadManager(
        service_name="kb-worker-unit",
        lane_policies={
            "control-io": LanePolicy(
                name="control-io",
                max_workers=2,
                max_queue_size=4,
                queue_timeout_seconds=0,
                cancel_grace_seconds=1,
                shutdown_grace_seconds=3,
            )
        },
    )
    manager.start()
    set_default_thread_manager(manager)

    async def db(action, *args, **kwargs):
        return await run_blocking(
            "unit-records", action, *args, lane="control-io", owner="unit", **kwargs
        )

    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=sa.pool.StaticPool,
        execution_options={"schema_translate_map": {"nexent": None}},
    )
    files.create(engine)
    jobs.create(engine)
    actor = ServicePrincipal("user", "tenant")
    records = bind_knowledge_jobs(
        StorageScope("runtime", "tenant", "user", {FILES, JOBS}), engine
    )
    policy = KnowledgeJobs(records, authorize=lambda *a, **kw: None)
    source = ObjectReference(
        space="files",
        key="source",
        version="etag:source",
        sha256=hashlib.sha256(b"source").hexdigest(),
    )
    content = "worker content"
    artifact = CleanseArtifact(
        source=source,
        parser_version="v2",
        blocks=[
            CleanseBlock(
                ordinal=0,
                kind="text",
                content=content,
                sha256=hashlib.sha256(content.encode()).hexdigest(),
            )
        ],
    )
    data = artifact.model_dump_json().encode()
    reference = ObjectReference(
        space="files",
        key="artifact",
        version="etag:artifact",
        sha256=hashlib.sha256(data).hexdigest(),
    )
    request = KnowledgeFileUpload(
        knowledge_id=1,
        file_id="a" * 32,
        file_version=0,
        artifact=reference,
        parser_version="v2",
        idempotency_key="upload",
        embedding_model={"model_id": 2, "revision": "v1"},
        chunking_strategy="none",
    )
    context = OperationContext("worker", monotonic() + 5)
    state = await db(policy.submit, request, context=context)
    lookup = KnowledgeJobLookup(
        knowledge_id=1, file_id=request.file_id, file_version=0, job_id=state.job_id
    )
    grant = KnowledgeFileGrant(
        knowledge_id=1,
        file_id=request.file_id,
        file_version=0,
        action="execute",
        source=source,
        filename="source.txt",
        collection="kb",
        artifact=reference,
        parser_version="v2",
        embedding_model_id=2,
    )
    client = SimpleNamespace(authorize_knowledge=AsyncMock(return_value=grant))
    models = SimpleNamespace(
        embedding_dimensions=AsyncMock(return_value=2),
        get=AsyncMock(
            return_value=SimpleNamespace(
                model_id=2, model_type="embedding", revision="v1"
            )
        ),
        invoke=AsyncMock(return_value=ModelResult(revision="v1", output=[[1.0, 0.5]])),
    )
    objects = Mock(
        scope=StorageScope("runtime", "tenant", "user", {"files"}),
        stat=Mock(
            return_value=ObjectMetadata(
                ObjectRef("files", "artifact", Revision(reference.version)),
                len(data),
                "application/json",
                sha256=reference.sha256,
            )
        ),
        open_read=Mock(side_effect=lambda *a, **kw: io.BytesIO(data)),
    )
    vectors = Mock(
        scope=StorageScope("runtime", "tenant", "user", {"kb"}),
        describe_collection=Mock(return_value=VectorCollectionInfo("kb", 2, "cosine")),
        upsert=Mock(return_value=(WriteReceipt("one", True),)),
    )
    closed = []

    @contextmanager
    def execution_ports(*args, **kwargs):
        try:
            yield objects, vectors
        finally:
            closed.append(True)

    @contextmanager
    def job_ports(*args, **kwargs):
        yield policy

    @contextmanager
    def record_ports(*args, **kwargs):
        yield records

    mocker.patch(
        "runtime.knowledge_base.worker.knowledge_runtime_ports",
        side_effect=record_ports,
    )
    worker = KnowledgeUploadWorker(
        client,
        models,
        jobs=job_ports,
        ports=execution_ports,
        max_artifact_bytes=10000,
        max_source_bytes=10000,
    )
    yield SimpleNamespace(**locals())
    drained = await manager.shutdown(timeout=3)
    clear_default_thread_manager(manager)
    assert not drained.stuck_execution_ids
    records.close()
    engine.dispose()


async def test_worker_publishes_confirmed_generation_and_duplicate_never_runs_models(
    setup,
):
    s = setup
    result = await s.worker.process(
        s.lookup, s.actor, owner_id="owner", context=s.context
    )
    assert result.status == "completed" and s.closed == [True]
    persisted = await s.db(s.records.get, JOBS, s.state.job_id, context=s.context)
    assert persisted["writer_ended"] and not persisted["reconcile_required"]
    assert await s.db(
        s.policy.is_visible, s.lookup, persisted["attempt_id"], context=s.context
    )
    assert (
        await s.worker.process(s.lookup, s.actor, owner_id="owner", context=s.context)
        == result
    )
    assert s.models.invoke.await_count == 1 and s.vectors.upsert.call_count == 1
    assert all(
        call.args[0].action == "execute"
        for call in s.client.authorize_knowledge.call_args_list
    )


async def test_unknown_upsert_never_publishes_or_marks_writer_ended(setup):
    s = setup
    s.vectors.upsert.side_effect = OutcomeUnknown()
    with pytest.raises(OutcomeUnknown):
        await s.worker.process(s.lookup, s.actor, owner_id="owner", context=s.context)
    row = await s.db(s.records.get, JOBS, s.state.job_id, context=s.context)
    assert (
        row["status"] == "failed"
        and row["reconcile_required"]
        and not row["writer_ended"]
    )
    assert not await s.db(
        s.policy.is_visible, s.lookup, row["attempt_id"], context=s.context
    )
    assert s.closed == [True] and s.vectors.upsert.call_count == 1


async def test_delete_during_model_call_blocks_vector_write_and_final_publication(
    setup,
):
    s = setup

    async def invoke(*args):
        await s.db(
            s.policy.submit,
            KnowledgeFileDelete(
                knowledge_id=1,
                file_id=s.lookup.file_id,
                file_version=0,
                idempotency_key="delete",
            ),
            context=s.context,
        )
        return ModelResult(revision="v1", output=[[1.0, 0.5]])

    s.models.invoke.side_effect = invoke
    with pytest.raises(OperationCancelled):
        await s.worker.process(s.lookup, s.actor, owner_id="owner", context=s.context)
    row = await s.db(s.records.get, JOBS, s.state.job_id, context=s.context)
    assert row["status"] == "cancelled" and row["writer_ended"]
    s.vectors.upsert.assert_not_called()


async def test_changed_grant_after_model_call_stops_before_upsert(setup):
    s = setup
    s.client.authorize_knowledge.side_effect = [
        s.grant,
        s.grant,
        s.grant.model_copy(update={"collection": "other"}),
    ]
    with pytest.raises(Conflict):
        await s.worker.process(s.lookup, s.actor, owner_id="owner", context=s.context)
    s.vectors.upsert.assert_not_called()
    row = await s.db(s.records.get, JOBS, s.state.job_id, context=s.context)
    assert row["status"] == "failed" and row["writer_ended"]


async def test_cancelled_attempt_cannot_publish_from_a_delayed_record_callback(
    setup, mocker
):
    s = setup
    entered, released, finished = asyncio.Event(), Event(), Event()
    loop = asyncio.get_running_loop()
    original = s.policy.complete

    def delayed(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        try:
            assert released.wait(2)
            return original(*args, **kwargs)
        finally:
            finished.set()

    mocker.patch.object(s.policy, "complete", side_effect=delayed)
    task = asyncio.create_task(
        s.worker.process(s.lookup, s.actor, owner_id="owner", context=s.context)
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        released.set()
    await s.db(lambda: finished.wait(1))
    row = await s.db(s.records.get, JOBS, s.state.job_id, context=s.context)
    assert row["status"] == "failed" and row["writer_ended"]
    assert not await s.db(
        s.policy.is_visible, s.lookup, row["attempt_id"], context=s.context
    )


async def test_cancelled_inflight_write_keeps_cleanup_blocked(setup):
    s = setup
    entered, released = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()

    def blocked(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        assert released.wait(2)
        return (WriteReceipt("late", True),)

    s.vectors.upsert.side_effect = blocked
    task = asyncio.create_task(
        s.worker.process(s.lookup, s.actor, owner_id="owner", context=s.context)
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        row = await s.db(s.records.get, JOBS, s.state.job_id, context=s.context)
        assert (
            row["status"] == "failed"
            and row["reconcile_required"]
            and not row["writer_ended"]
        )
        assert not await s.db(
            s.policy.is_visible, s.lookup, row["attempt_id"], context=s.context
        )
    finally:
        released.set()


@pytest.mark.parametrize(
    "actor", [ServicePrincipal("other", "tenant"), ServicePrincipal("user", "other")]
)
async def test_wrong_worker_identity_never_requests_a_grant(setup, actor):
    s = setup
    with pytest.raises(NotFound):
        await s.worker.process(s.lookup, actor, owner_id="owner", context=s.context)
    s.client.authorize_knowledge.assert_not_awaited()
    s.models.invoke.assert_not_awaited()


async def test_corrupt_payload_is_not_executed_or_reauthorized(setup):
    s = setup
    changed = {**s.request.model_dump(mode="json"), "parser_version": "changed"}
    await s.db(
        s.records.patch,
        JOBS,
        s.state.job_id,
        FieldPatch(set_values={"request_payload": changed}),
        context=s.context,
    )
    with pytest.raises(InvalidInput):
        await s.worker.process(s.lookup, s.actor, owner_id="owner", context=s.context)
    s.client.authorize_knowledge.assert_not_awaited()
    s.models.invoke.assert_not_awaited()
