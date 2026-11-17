# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real CAS and live DAC surround controlled child submission boundaries."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from contracts.agentos_knowledge import KnowledgeJobState
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from contracts.knowledge_cleanse import KnowledgeCleanseState
from management.services.knowledge_base.ingestion_coordinator import (
    IngestionCoordinator,
)
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, NotFound, ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from infrastructure.rdb.knowledge_ingestion import bind_ingestion_records
from test.backend.infrastructure.test_knowledge_ingestion_records import (
    records,  # noqa: F401
)
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_contract import intent


@pytest.fixture
def sqlite_threads(monkeypatch):
    create = sa.create_engine

    def engine(url, **kwargs):
        assert url == "sqlite://"
        return create(
            url,
            poolclass=sa.pool.StaticPool,
            connect_args={"check_same_thread": False},
            **kwargs,
        )

    monkeypatch.setattr(sa, "create_engine", engine)


@pytest.fixture
async def setup(sqlite_threads, records, resources):  # noqa: F811

    port, engine, table = records
    _, update, resource_engine, resource_tables = resources
    update("cleanse_knowledge", embedding_model_id=2)
    value = intent()
    update(
        "cleanse_files",
        source_space=value.source.space,
        source_key=value.source.key,
        source_revision=value.source.version,
        source_sha256=value.source.sha256,
    )
    actor = SimpleNamespace(user_id="user-a", tenant_id="tenant-a")
    counters = {"open": 0, "close": 0}
    manager = ThreadManager(
        service_name="ingestion-ut",
        lane_policies={
            "control-io": LanePolicy(
                name="control-io",
                max_workers=1,
                max_queue_size=8,
                queue_timeout_seconds=1,
                cancel_grace_seconds=1,
                shutdown_grace_seconds=2,
            ),
        },
    )
    manager.start()
    set_default_thread_manager(manager)

    @contextmanager
    def ports(tenant_id, user_id, *, context):
        assert (tenant_id, user_id) == (actor.tenant_id, actor.user_id)
        context.remaining()
        counters["open"] += 1
        bound = bind_ingestion_records(port.scope, engine)
        authorized = bind_cleanse_resources(
            StorageScope("management", tenant_id, user_id, set(resource_tables)),
            resource_engine,
        )
        try:
            yield bound, authorized
        finally:
            bound.close()
            authorized.close()
            counters["close"] += 1

    cleanse = Mock(parser_version=value.parser_version)
    client = SimpleNamespace(
        get_model=AsyncMock(
            return_value=SimpleNamespace(
                model_id=2, model_type="embedding", revision="model-v1"
            )
        ),
        upload_knowledge_file=AsyncMock(),
        inspect_knowledge_file=AsyncMock(),
    )
    coordinator = IngestionCoordinator(cleanse, client, ports=ports)

    def row():
        with engine.connect() as connection:
            return dict(connection.execute(sa.select(table)).mappings().one())

    def child(status="queued", **extra):
        return KnowledgeCleanseState(
            **value._reference(),
            job_id=row()["process_task_id"],
            status=status,
            **extra,
        )

    def runtime(status="queued"):
        return KnowledgeJobState(
            **value._reference(), job_id=row()["forward_task_id"], status=status
        )

    state = SimpleNamespace(**locals())
    try:
        yield state
    finally:
        clear_default_thread_manager(manager)
        drained = await manager.shutdown(timeout=2)
        assert not drained.stuck_execution_ids
        assert counters["open"] == counters["close"]


@pytest.mark.asyncio
async def test_admission_and_each_child_are_reserved_before_single_submission(setup):
    s = setup
    admitted = await s.coordinator.admit(s.value, s.actor, context=context())
    assert admitted["stage"] == "INGEST_ACCEPTED"

    def submit(*args, **kwargs):
        assert s.row()["stage"] == "CLEANSE_SUBMITTING"
        return s.child()

    s.cleanse.submit.side_effect = submit
    assert (await s.coordinator.advance(s.value.file_id, s.actor, context=context()))[
        "stage"
    ] == "CLEANSE_PENDING"
    s.cleanse.inspect.side_effect = lambda *args, **kwargs: s.child(
        "completed", artifact=s.value.source
    )

    async def upload(payload, **kwargs):
        assert s.row()["stage"] == "RUNTIME_SUBMITTING"
        assert payload == s.value.runtime_request(s.value.source)
        assert kwargs == {"user_id": "user-a", "tenant_id": "tenant-a"}
        return s.runtime()

    s.client.upload_knowledge_file.side_effect = upload
    assert (await s.coordinator.advance(s.value.file_id, s.actor, context=context()))[
        "stage"
    ] == "RUNTIME_PENDING"
    s.client.inspect_knowledge_file.side_effect = lambda *args, **kwargs: s.runtime(
        "completed"
    )
    final = await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    assert final["status"] == "COMPLETED" and final["completed_at"]
    await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    s.cleanse.submit.assert_called_once()
    s.client.upload_knowledge_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_lost_cleanse_response_only_inspects_original_id_even_when_missing(setup):
    s = setup
    await s.coordinator.admit(s.value, s.actor, context=context())
    s.cleanse.submit.side_effect = RuntimeError("lost response")
    with pytest.raises(RuntimeError, match="lost response"):
        await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    reserved = s.row()
    s.cleanse.inspect.side_effect = NotFound()
    result = await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    assert (
        result["version"] == reserved["version"]
        and result["stage"] == "CLEANSE_SUBMITTING"
    )
    assert s.cleanse.inspect.call_args.args[0].job_id == reserved["process_task_id"]
    s.cleanse.submit.assert_called_once()


@pytest.mark.asyncio
async def test_lost_runtime_response_preserves_id_and_404_does_not_resubmit(setup):
    s = setup
    await s.coordinator.admit(s.value, s.actor, context=context())
    s.cleanse.submit.side_effect = lambda *args, **kwargs: s.child(
        "completed", artifact=s.value.source
    )
    s.client.upload_knowledge_file.side_effect = RuntimeServiceTimeoutError()
    with pytest.raises(RuntimeServiceTimeoutError):
        await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    reserved = s.row()
    s.client.inspect_knowledge_file.side_effect = RuntimeUpstreamError(404, b"", {})
    result = await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    assert (
        result["version"] == reserved["version"]
        and result["stage"] == "RUNTIME_SUBMITTING"
    )
    s.client.inspect_knowledge_file.side_effect = lambda *args, **kwargs: s.runtime(
        "completed"
    )
    assert (await s.coordinator.advance(s.value.file_id, s.actor, context=context()))[
        "status"
    ] == "COMPLETED"
    s.client.upload_knowledge_file.assert_awaited_once()
    assert (
        s.client.inspect_knowledge_file.call_args.args[0].job_id
        == reserved["forward_task_id"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["permission", "source", "model"])
async def test_current_resource_changes_block_submission(setup, change):
    s = setup
    await s.coordinator.admit(s.value, s.actor, context=context())
    if change == "permission":
        s.update("cleanse_memberships", delete_flag="Y")
    elif change == "source":
        s.update("cleanse_files", source_generation=1)
    else:
        s.update("cleanse_knowledge", embedding_model_id=3)
    with pytest.raises((ScopeDenied, Conflict)):
        await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    assert s.row()["stage"] == "INGEST_ACCEPTED"
    s.cleanse.submit.assert_not_called()


@pytest.mark.asyncio
async def test_replaced_model_revision_rejects_admission_without_intent(setup):
    s = setup
    s.client.get_model.return_value.revision = "new-revision"
    with pytest.raises(Conflict):
        await s.coordinator.admit(s.value, s.actor, context=context())
    assert s.row()["ingestion_request"] is None


@pytest.mark.asyncio
async def test_revocation_after_child_response_blocks_late_projection(setup):
    s = setup
    await s.coordinator.admit(s.value, s.actor, context=context())

    def submit(*args, **kwargs):
        s.update("cleanse_memberships", delete_flag="Y")
        return s.child()

    s.cleanse.submit.side_effect = submit
    with pytest.raises(ScopeDenied):
        await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    assert s.row()["stage"] == "CLEANSE_SUBMITTING"


@pytest.mark.asyncio
async def test_total_deadline_cancels_stalled_model_lookup_without_admission(setup):
    from time import monotonic

    from nexent.storage.models import OperationContext

    s = setup
    stopped = asyncio.Event()

    async def stalled(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    s.client.get_model.side_effect = stalled
    with pytest.raises(DeadlineExceeded):
        await s.coordinator.admit(
            s.value, s.actor, context=OperationContext("deadline", monotonic() + 0.05)
        )
    assert stopped.is_set() and s.row()["ingestion_request"] is None
    s.client.get_model.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_during_child_submission_fences_result(setup):
    s = setup
    await s.coordinator.admit(s.value, s.actor, context=context())

    def submit(*args, **kwargs):
        with s.engine.begin() as conn:
            conn.execute(
                s.table.update().values(
                    status="DELETE_REQUESTED", version=s.table.c.version + 1
                )
            )
        return s.child()

    s.cleanse.submit.side_effect = submit
    with pytest.raises(Conflict):
        await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    assert s.row()["status"] == "DELETE_REQUESTED"
    s.client.upload_knowledge_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_two_coordinators_with_same_snapshot_only_submit_one_cleanse(setup):
    s = setup
    await s.coordinator.admit(s.value, s.actor, context=context())
    arrived, release = 0, asyncio.Event()
    metadata = s.client.get_model.return_value

    async def synchronize(*args, **kwargs):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            release.set()
        await release.wait()
        return metadata

    s.client.get_model.side_effect = synchronize
    s.cleanse.submit.side_effect = lambda *args, **kwargs: s.child()
    second = IngestionCoordinator(s.cleanse, s.client, ports=s.ports)
    results = await asyncio.gather(
        s.coordinator.advance(s.value.file_id, s.actor, context=context()),
        second.advance(s.value.file_id, s.actor, context=context()),
        return_exceptions=True,
    )
    assert sum(isinstance(result, Conflict) for result in results) == 1
    assert sum(isinstance(result, dict) for result in results) == 1
    s.cleanse.submit.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 409, 500])
async def test_runtime_lookup_only_treats_404_as_unconfirmed(setup, code):
    s = setup
    await s.coordinator.admit(s.value, s.actor, context=context())
    s.cleanse.submit.side_effect = lambda *args, **kwargs: s.child(
        "completed", artifact=s.value.source
    )
    s.client.upload_knowledge_file.side_effect = lambda *args, **kwargs: s.runtime()
    await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    s.client.inspect_knowledge_file.side_effect = RuntimeUpstreamError(
        code, b"sensitive", {}
    )
    with pytest.raises(RuntimeUpstreamError) as error:
        await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    assert error.value.status_code == code and s.row()["stage"] == "RUNTIME_PENDING"
    s.client.upload_knowledge_file.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["cleanse", "runtime"])
async def test_confirmed_child_failure_is_projected_without_reexecution(setup, phase):
    s = setup
    await s.coordinator.admit(s.value, s.actor, context=context())
    s.cleanse.submit.side_effect = lambda *args, **kwargs: (
        s.child(
            "failed",
            error_code="PARSER_FAILED",
        )
        if phase == "cleanse"
        else s.child("completed", artifact=s.value.source)
    )
    s.client.upload_knowledge_file.side_effect = lambda *args, **kwargs: s.runtime(
        "failed"
    )
    row = await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    assert row["status"] == "FAILED"
    assert row["error_stage"] == ("PROCESS" if phase == "cleanse" else "FORWARD")
    await s.coordinator.advance(s.value.file_id, s.actor, context=context())
    s.cleanse.submit.assert_called_once()
    assert s.client.upload_knowledge_file.await_count == (
        0 if phase == "cleanse" else 1
    )


@pytest.mark.asyncio
async def test_cancelled_request_signals_owned_blocking_context_and_drains(
    setup, monkeypatch
):
    from threading import Event

    from nexent.storage.errors import OperationCancelled

    s = setup
    entered, finished = asyncio.Event(), asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()
    observed = []
    original = s.coordinator._load

    def blocked(file_id, actor, operation, intent):
        observed.append(operation)
        loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(2)
            with pytest.raises(OperationCancelled):
                original(file_id, actor, operation, intent)
        finally:
            loop.call_soon_threadsafe(finished.set)

    monkeypatch.setattr(s.coordinator, "_load", blocked)
    task = asyncio.create_task(s.coordinator.admit(s.value, s.actor, context=context()))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert observed[0].cancelled.is_set()
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
    assert s.row()["ingestion_request"] is None
    s.client.get_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_logs_one_safe_warning_without_duplicate_error(setup, caplog):
    from time import monotonic

    from nexent.storage.models import OperationContext

    s = setup

    async def stalled(*args, **kwargs):
        await asyncio.Event().wait()

    s.client.get_model.side_effect = stalled
    with caplog.at_level("WARNING"), pytest.raises(DeadlineExceeded):
        await s.coordinator.admit(
            s.value, s.actor, context=OperationContext("safe-op", monotonic() + 0.05)
        )
    logged = [
        record
        for record in caplog.records
        if record.name.endswith("ingestion_coordinator")
    ]
    assert len(logged) == 1 and logged[0].levelname == "WARNING"
    assert "operation_id=safe-op" in logged[0].message
    assert "source.txt" not in logged[0].message and "model-v1" not in logged[0].message


@pytest.mark.asyncio
async def test_accept_freezes_authorized_file_and_model_then_replays_exact_intent(
    setup,
):
    s = setup
    first = await s.coordinator.accept(s.value.file_id, s.actor, context=context())
    assert first["ingestion_request"] == s.value.model_dump(mode="json")
    s.client.get_model.assert_awaited_once_with(
        2, user_id="user-a", tenant_id="tenant-a"
    )
    repeated = await s.coordinator.accept(s.value.file_id, s.actor, context=context())
    assert repeated["version"] == first["version"]
    with pytest.raises(Conflict):
        await s.coordinator.accept(
            s.value.file_id, s.actor, chunking_strategy="none", context=context()
        )
    s.cleanse.submit.assert_not_called()


@pytest.mark.asyncio
async def test_accept_cannot_replace_already_pinned_model_revision(setup):
    s = setup
    await s.coordinator.accept(s.value.file_id, s.actor, context=context())
    s.client.get_model.return_value.revision = "changed"
    with pytest.raises(Conflict):
        await s.coordinator.accept(s.value.file_id, s.actor, context=context())
    assert s.row()["ingestion_request"] == s.value.model_dump(mode="json")
