# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Chunk admission and existing file/collection lifecycle share real SI transactions."""

from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from contracts.agentos_knowledge import (
    KnowledgeFileDelete,
    KnowledgeFileUpload,
    KnowledgeJobLookup,
)
from contracts.knowledge_base_deletion import (
    KnowledgeBaseDelete,
    KnowledgeBaseDeleteGrant,
)
from contracts.knowledge_chunk_mutation import CHANGES, STATES, ChunkMutationIntent
from nexent.storage.errors import Conflict, InvalidInput, NotFound, ScopeDenied
from nexent.storage.models import (
    OperationContext,
    PageRequest,
    RecordQuery,
    StorageScope,
)
from runtime.knowledge_base.base_deletion import KnowledgeBaseDeletionJournal
from runtime.knowledge_base.chunk_admission import ChunkMutationAdmission
from runtime.knowledge_base.jobs import KnowledgeJobs

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.knowledge_base_deletions import deletions
from infrastructure.rdb.knowledge_chunk_mutations import changes, states
from infrastructure.rdb.knowledge_dispatch import DATASET, bind_knowledge_dispatch
from infrastructure.rdb.knowledge_jobs import FILES, JOBS, files, jobs
from infrastructure.rdb.knowledge_lifecycle import bind_knowledge_lifecycle


def context():
    return OperationContext("chunk-fence-ut", monotonic() + 15)


@pytest.fixture
def lifecycle():
    engine = sa.create_engine(
        "sqlite://", execution_options={"schema_translate_map": {"nexent": None}}
    )
    for table in (files, jobs, changes, states, deletions):
        table.create(engine)
    actor = ServicePrincipal("operator", "tenant-a")
    scope = StorageScope("runtime", actor.tenant_id, actor.user_id, {FILES, JOBS})
    record = bind_knowledge_lifecycle(scope, engine, mode="jobs")
    mutation_records = bind_knowledge_lifecycle(scope, engine, mode="mutation")
    delete_records = bind_knowledge_lifecycle(scope, engine, mode="deletion")
    authorize = Mock()
    policy = KnowledgeJobs(record, authorize=authorize)
    mutation = ChunkMutationAdmission(mutation_records, 1)
    grant = KnowledgeBaseDeleteGrant(knowledge_id=1, collection="collection")
    base = KnowledgeBaseDeletionJournal(delete_records, actor, grant)
    request = KnowledgeFileUpload(
        knowledge_id=1,
        file_id="a" * 32,
        file_version=1,
        artifact={
            "space": "files",
            "key": "artifact",
            "version": "v1",
            "sha256": "a" * 64,
        },
        parser_version="v2",
        idempotency_key="upload",
        embedding_model={"model_id": 2, "revision": "r1"},
    )
    try:
        yield SimpleNamespace(**locals())
    finally:
        for port in (record, mutation_records, delete_records):
            port.close()
        engine.dispose()


def lookup(state):
    return KnowledgeJobLookup(
        **state.model_dump(
            include={"knowledge_id", "file_id", "file_version", "job_id"}
        )
    )


def publish(s, request=None):
    request = request or s.request
    state = s.policy.submit(request, context=context())
    handle = s.policy.claim(
        lookup(state), owner_id="owner", lease_seconds=30, context=context()
    )
    assert s.policy.begin_execution(handle, context=context())
    assert s.policy.complete(handle, chunk_count=3, context=context())
    return handle


def intent(s, handle=None, *, key="edit", chunk="chunk", operation="update"):
    values = {
        "knowledge_id": 1,
        "chunk_id": chunk,
        "request_key": key,
        "operation": operation,
        "resource_revision": "b" * 64,
        "changes": {} if operation == "delete" else {"content": "new"},
    }
    if handle is not None:
        values.update(
            file_ref={
                "knowledge_id": 1,
                "file_id": handle["file_id"],
                "file_version": handle["file_version"],
            },
            generation=handle["attempt_id"],
            chunk_index=1,
        )
    return ChunkMutationIntent(**values)


def delete_file(s, version=1):
    return s.policy.submit(
        KnowledgeFileDelete(
            knowledge_id=1,
            file_id=s.request.file_id,
            file_version=version,
            idempotency_key="delete",
        ),
        context=context(),
    )


def dispatched(s):
    port = bind_knowledge_dispatch(s.engine)
    try:
        return {
            row["job_id"]
            for row in port.query(
                DATASET, RecordQuery(), PageRequest(), context=context()
            ).items
        }
    finally:
        port.close()


def test_real_published_file_admits_once_and_preserves_actual_actor(lifecycle):
    s = lifecycle
    handle = publish(s)
    value = intent(s, handle)
    row, fresh = s.mutation.reserve(value, context=context())
    assert (
        fresh
        and row["user_id"] == s.actor.user_id
        and row["tenant_id"] == s.actor.tenant_id
    )
    assert s.mutation.reserve(value, context=context()) == (row, False)


@pytest.mark.parametrize(
    "change",
    [
        {"generation": "wrong"},
        {"file_ref": {"knowledge_id": 1, "file_id": "a" * 32, "file_version": 2}},
    ],
)
def test_stale_generation_or_version_never_creates_a_mutation(lifecycle, change):
    s = lifecycle
    value = intent(s, publish(s)).model_copy(update=change)
    with pytest.raises(Conflict):
        s.mutation.reserve(value, context=context())
    assert s.mutation_records.count(CHANGES, RecordQuery(), context=context()) == 0


def test_missing_file_cannot_be_invented_by_chunk_admission(lifecycle):
    s = lifecycle
    handle = {"file_id": s.request.file_id, "file_version": 1, "attempt_id": "missing"}
    with pytest.raises(NotFound):
        s.mutation.reserve(intent(s, handle), context=context())


def test_tombstone_wins_before_mutation_admission(lifecycle):
    s = lifecycle
    handle = publish(s)
    delete_file(s)
    with pytest.raises(Conflict):
        s.mutation.reserve(intent(s, handle), context=context())


@pytest.mark.parametrize("status", ["reserved", "writing", "unknown"])
def test_active_chunk_blocks_file_cleanup_even_after_tombstone(lifecycle, status):
    s = lifecycle
    row, _ = s.mutation.reserve(intent(s, publish(s)), context=context())
    if status != "reserved":
        s.mutation.begin(row["mutation_id"], context=context())
    if status == "unknown":
        s.mutation.mark_unknown(
            row["mutation_id"],
            writer_ended=True,
            error_code="UNKNOWN",
            context=context(),
        )
    deleting = lookup(delete_file(s))
    assert not s.policy.cleanup_ready(deleting, context=context())
    assert deleting.job_id not in dispatched(s)
    assert (
        s.policy.begin_delete(deleting, owner_id="cleaner", context=context()) is None
    )
    with pytest.raises(Conflict):
        s.base.reserve(
            KnowledgeBaseDelete(knowledge_id=1, idempotency_key="kb-delete"),
            context=context(),
        )


def test_known_no_effect_failure_releases_file_cleanup(lifecycle):
    s = lifecycle
    row, _ = s.mutation.reserve(intent(s, publish(s)), context=context())
    deleting = lookup(delete_file(s))
    assert not s.policy.cleanup_ready(deleting, context=context())
    assert deleting.job_id not in dispatched(s)
    s.mutation.fail(
        row["mutation_id"],
        known_not_applied=True,
        error_code="REJECTED",
        context=context(),
    )
    assert s.policy.cleanup_ready(deleting, context=context())
    assert deleting.job_id in dispatched(s)
    assert (
        s.policy.begin_delete(deleting, owner_id="cleaner", context=context())
        is not None
    )


def test_kb_reservation_closes_standalone_and_upload_admission_for_other_actor(
    lifecycle,
):
    s = lifecycle
    s.base.reserve(
        KnowledgeBaseDelete(knowledge_id=1, idempotency_key="kb-delete"),
        context=context(),
    )
    other_scope = StorageScope("runtime", "tenant-a", "another-user", {FILES, JOBS})
    other = bind_knowledge_lifecycle(other_scope, s.engine, mode="mutation")
    try:
        with pytest.raises(Conflict):
            ChunkMutationAdmission(other, 1).reserve(intent(s), context=context())
        with pytest.raises(Conflict):
            s.policy.submit(s.request, context=context())
    finally:
        other.close()


def test_active_standalone_blocks_kb_but_not_unrelated_file(lifecycle):
    s = lifecycle
    row, _ = s.mutation.reserve(intent(s), context=context())
    publish(s)
    deleting = lookup(delete_file(s))
    assert s.policy.cleanup_ready(deleting, context=context())
    assert deleting.job_id in dispatched(s)
    with pytest.raises(Conflict):
        s.base.reserve(
            KnowledgeBaseDelete(knowledge_id=1, idempotency_key="kb-delete"),
            context=context(),
        )
    s.mutation.fail(
        row["mutation_id"],
        known_not_applied=True,
        error_code="REJECTED",
        context=context(),
    )
    assert s.base.reserve(
        KnowledgeBaseDelete(knowledge_id=1, idempotency_key="kb-delete"),
        context=context(),
    )[1]


def test_same_version_rebuild_cannot_start_while_chunk_is_active(lifecycle):
    s = lifecycle
    row, _ = s.mutation.reserve(intent(s, publish(s)), context=context())
    newer = s.request.model_copy(update={"idempotency_key": "new"})
    queued = s.policy.submit(newer, context=context())
    assert queued.job_id not in dispatched(s)
    handle = s.policy.claim(
        lookup(queued), owner_id="new-owner", lease_seconds=30, context=context()
    )
    assert not s.policy.begin_execution(handle, context=context())
    s.mutation.fail(
        row["mutation_id"],
        known_not_applied=True,
        error_code="REJECTED",
        context=context(),
    )
    assert s.policy.begin_execution(handle, context=context())


def test_new_file_version_upload_uses_separate_keys_and_can_start(lifecycle):
    s = lifecycle
    s.mutation.reserve(intent(s, publish(s)), context=context())
    newer = s.request.model_copy(update={"file_version": 2, "idempotency_key": "new"})
    queued = s.policy.submit(newer, context=context())
    handle = s.policy.claim(
        lookup(queued), owner_id="new-owner", lease_seconds=30, context=context()
    )
    assert s.policy.begin_execution(handle, context=context())


def test_rejected_admission_rolls_back_marker_creation(lifecycle):
    s = lifecycle
    with pytest.raises(NotFound):
        s.mutation.reserve(
            intent(
                s,
                {"file_id": s.request.file_id, "file_version": 1, "attempt_id": "none"},
            ),
            context=context(),
        )
    assert s.mutation_records.count(STATES, RecordQuery(), context=context()) == 0
    assert s.mutation_records.count(CHANGES, RecordQuery(), context=context()) == 0


def test_another_kb_still_accepts_upload_after_collection_deletion(lifecycle):
    s = lifecycle
    s.base.reserve(
        KnowledgeBaseDelete(knowledge_id=1, idempotency_key="kb-delete"),
        context=context(),
    )
    state = s.policy.submit(
        s.request.model_copy(update={"knowledge_id": 2}), context=context()
    )
    assert state.knowledge_id == 2 and state.status == "queued"


def test_collection_deletion_different_request_cannot_acquire_a_second_owner(lifecycle):
    s = lifecycle
    first = KnowledgeBaseDelete(knowledge_id=1, idempotency_key="first")
    row, owner = s.base.reserve(first, context=context())
    assert owner
    assert s.base.reserve(first, context=context()) == (row, False)
    with pytest.raises(Conflict):
        s.base.reserve(
            first.model_copy(update={"idempotency_key": "second"}), context=context()
        )


@pytest.mark.parametrize("writable", [1, "true", None])
def test_job_binding_rejects_non_boolean_write_policy(lifecycle, writable):
    from infrastructure.rdb.knowledge_jobs import bind_knowledge_jobs

    with pytest.raises(InvalidInput):
        bind_knowledge_jobs(lifecycle.scope, lifecycle.engine, writable=writable)


@pytest.mark.parametrize(
    "changed",
    [
        {"service_role": "management"},
        {"system": True, "tenant_id": None},
        {"resource_prefix": "prefix/"},
    ],
)
def test_non_runtime_or_unbounded_lifecycle_handles_are_denied(lifecycle, changed):
    from dataclasses import replace

    with pytest.raises(ScopeDenied):
        bind_knowledge_lifecycle(
            replace(lifecycle.scope, **changed), lifecycle.engine, mode="mutation"
        )


@pytest.mark.parametrize(
    "mode,dataset", [("mutation", JOBS), ("jobs", CHANGES), ("deletion", FILES)]
)
def test_fixed_lifecycle_bindings_do_not_grant_unrelated_writes(
    lifecycle, mode, dataset
):
    from nexent.storage.models import FieldPatch

    s = lifecycle
    port = bind_knowledge_lifecycle(s.scope, s.engine, mode=mode)
    try:
        with pytest.raises(ScopeDenied):
            port.patch(dataset, "missing", FieldPatch(set_values={}), context=context())
    finally:
        port.close()
