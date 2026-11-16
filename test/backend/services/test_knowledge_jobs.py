# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Durable Runtime job policy with real scoped SQL records and no business mocks."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from contracts.agentos_knowledge import (
    KnowledgeFileDelete,
    KnowledgeFileUpload,
    KnowledgeJobLookup,
)
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    OperationContext,
    StorageScope,
    WriteOutcome,
    WriteReceipt,
)
from runtime.knowledge_base.jobs import KnowledgeJobs

from infrastructure.rdb.knowledge_jobs import (
    FILES,
    JOBS,
    bind_knowledge_jobs,
    files,
    jobs,
)


@pytest.fixture
def setup():
    from time import monotonic

    engine = sa.create_engine(
        "sqlite://", execution_options={"schema_translate_map": {"nexent": None}}
    )
    files.create(engine)
    jobs.create(engine)
    scope = StorageScope("runtime", "tenant", "user", {FILES, JOBS})
    records = bind_knowledge_jobs(scope, engine)
    now = [datetime(2026, 11, 16, tzinfo=timezone.utc)]
    authorize = Mock()
    service = KnowledgeJobs(records, authorize=authorize, clock=lambda: now[0])
    context = OperationContext("job-test", monotonic() + 15)
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
        embedding_model={"model_id": 2, "revision": "model-v1"},
    )
    yield service, records, engine, request, context, now, authorize
    records.close()
    engine.dispose()


def lookup(state):
    return KnowledgeJobLookup(
        **state.model_dump(
            include={"knowledge_id", "file_id", "file_version", "job_id"}
        )
    )


def started(setup):
    service, _, _, request, context, _, _ = setup
    state = service.submit(request, context=context)
    handle = service.claim(
        lookup(state), owner_id="owner", lease_seconds=30, context=context
    )
    assert service.begin_execution(handle, context=context)
    return state, handle


def test_admission_is_durable_and_same_key_checks_the_entire_request(setup):
    service, _, _, request, context, _, authorize = setup
    first = service.submit(request, context=context)
    assert service.submit(request, context=context) == first
    changed = request.model_copy(update={"parser_version": "other"})
    with pytest.raises(Conflict):
        service.submit(changed, context=context)
    assert service.inspect(lookup(first), context=context) == first
    assert authorize.call_count == 4


@pytest.mark.parametrize("tenant,user", [("other", "user"), ("tenant", "other")])
def test_inspection_and_claim_preserve_user_tenant_ownership(setup, tenant, user):
    service, _, engine, request, context, _, _ = setup
    state = service.submit(request, context=context)
    records = bind_knowledge_jobs(
        StorageScope("runtime", tenant, user, {FILES, JOBS}), engine
    )
    other = KnowledgeJobs(records, authorize=Mock())
    try:
        with pytest.raises(NotFound):
            other.inspect(lookup(state), context=context)
        with pytest.raises(NotFound):
            other.claim(
                lookup(state), owner_id="other", lease_seconds=10, context=context
            )
    finally:
        records.close()


def test_non_runtime_handles_are_denied(setup):
    _, _, engine, _, _, _, _ = setup
    with pytest.raises(ScopeDenied):
        bind_knowledge_jobs(
            StorageScope("management", "tenant", "user", {FILES, JOBS}), engine
        )


def test_expired_unstarted_claim_can_be_taken_over_but_old_attempt_is_fenced(setup):
    service, _, _, request, context, now, _ = setup
    state = service.submit(request, context=context)
    old = service.claim(
        lookup(state), owner_id="one", lease_seconds=10, context=context
    )
    now[0] += timedelta(seconds=11)
    new = service.claim(
        lookup(state), owner_id="two", lease_seconds=30, context=context
    )
    assert old["attempt_id"] != new["attempt_id"]
    assert not service.begin_execution(old, context=context)
    assert service.begin_execution(new, context=context)
    assert not service.begin_execution(new, context=context)


def test_execution_intent_prevents_expired_writer_replay(setup):
    service, records, _, _, context, now, _ = setup
    state, handle = started(setup)
    persisted = records.get(JOBS, state.job_id, context=context)
    assert persisted["write_started"] and not persisted["writer_ended"]
    assert persisted["reconcile_required"]
    now[0] += timedelta(seconds=31)
    assert (
        service.claim(
            lookup(state), owner_id="replacement", lease_seconds=30, context=context
        )
        is None
    )
    assert not service.complete(handle, chunk_count=2, context=context)


def test_completion_publishes_only_current_file_version_and_generation(setup):
    service, _, _, request, context, _, _ = setup
    _, handle = started(setup)
    assert not service.is_visible(request, handle["attempt_id"], context=context)
    assert service.complete(handle, chunk_count=2, context=context)
    assert service.is_visible(request, handle["attempt_id"], context=context)
    assert not service.is_visible(request, "different", context=context)
    assert not service.complete(handle, chunk_count=2, context=context)


def test_new_version_cancels_old_execution_and_blocks_its_publication(setup):
    service, _, _, request, context, _, _ = setup
    state, old = started(setup)
    newer = request.model_copy(update={"file_version": 2, "idempotency_key": "new"})
    service.submit(newer, context=context)
    assert service.inspect(lookup(state), context=context).status == "cancelled"
    assert not service.complete(old, chunk_count=1, context=context)
    assert service.end_attempt(old, writer_ended=True, context=context)


def test_same_version_cannot_start_another_writer_until_previous_has_ended(setup):
    service, _, _, request, context, _, _ = setup
    _, handle = started(setup)
    replacement = request.model_copy(update={"idempotency_key": "explicit-reprocess"})
    with pytest.raises(Conflict):
        service.submit(replacement, context=context)
    assert service.end_attempt(handle, writer_ended=True, context=context)
    assert service.submit(replacement, context=context).job_id != handle["job_id"]


def test_delete_hides_visibility_and_fences_late_completion(setup):
    service, _, _, request, context, _, _ = setup
    _, handle = started(setup)
    delete = KnowledgeFileDelete(
        **request.model_dump(include={"knowledge_id", "file_id", "file_version"}),
        idempotency_key="delete",
    )
    state = service.submit(delete, context=context)
    assert state.status == "cleanup_pending" and not state.physical_cleanup_complete
    assert not service.complete(handle, chunk_count=1, context=context)
    assert not service.is_visible(request, handle["attempt_id"], context=context)
    assert not service.cleanup_ready(lookup(state), context=context)
    assert service.end_attempt(handle, writer_ended=True, context=context)
    assert service.cleanup_ready(lookup(state), context=context)
    assert (
        service.finish_delete(
            lookup(state), physical_absence_confirmed=True, context=context
        ).status
        == "deleted"
    )
    assert service.submit(delete, context=context).physical_cleanup_complete
    with pytest.raises(Conflict):
        service.submit(
            request.model_copy(update={"idempotency_key": "resurrect"}), context=context
        )


def test_delete_does_not_hide_a_newer_visible_generation(setup):
    service, _, _, request, context, _, _ = setup
    newer = request.model_copy(update={"file_version": 2})
    state = service.submit(newer, context=context)
    handle = service.claim(
        lookup(state), owner_id="one", lease_seconds=30, context=context
    )
    assert service.begin_execution(handle, context=context)
    assert service.complete(handle, chunk_count=1, context=context)
    service.submit(
        KnowledgeFileDelete(
            knowledge_id=1,
            file_id=request.file_id,
            file_version=1,
            idempotency_key="old-delete",
        ),
        context=context,
    )
    assert service.is_visible(newer, handle["attempt_id"], context=context)


def test_cleanup_requires_explicit_absence_and_keeps_unknown_writer_blocked(setup):
    service, _, _, request, context, _, _ = setup
    _, handle = started(setup)
    service.end_attempt(handle, writer_ended=False, context=context)
    state = service.submit(
        KnowledgeFileDelete(
            knowledge_id=1,
            file_id=request.file_id,
            file_version=1,
            idempotency_key="delete",
        ),
        context=context,
    )
    assert not service.cleanup_ready(lookup(state), context=context)
    with pytest.raises(Conflict):
        service.finish_delete(
            lookup(state), physical_absence_confirmed=True, context=context
        )
    with pytest.raises(InvalidInput):
        service.finish_delete(
            lookup(state), physical_absence_confirmed=False, context=context
        )


def test_publication_rolls_back_job_when_manifest_write_fails(setup, monkeypatch):
    service, records, _, request, context, _, _ = setup
    state, handle = started(setup)
    original = type(records).patch

    def failing(store, dataset, key, patch, **kwargs):
        if dataset == FILES and patch.set_values.get("visible_job_id"):
            raise RuntimeError("controlled manifest failure")
        return original(store, dataset, key, patch, **kwargs)

    monkeypatch.setattr(type(records), "patch", failing)
    with pytest.raises(RuntimeError):
        service.complete(handle, chunk_count=2, context=context)
    assert service.inspect(lookup(state), context=context).status == "running"
    assert not service.is_visible(request, handle["attempt_id"], context=context)


def test_renewal_preserves_execution_intent_and_cancellation_stops_it(setup):
    service, records, _, request, context, now, _ = setup
    state, handle = started(setup)
    now[0] += timedelta(seconds=20)
    assert service.renew(handle, lease_seconds=30, context=context)
    now[0] += timedelta(seconds=20)
    assert records.get(JOBS, state.job_id, context=context)["reconcile_required"]
    assert service.renew(handle, lease_seconds=30, context=context)
    service.submit(
        KnowledgeFileDelete(
            knowledge_id=1,
            file_id=request.file_id,
            file_version=1,
            idempotency_key="delete",
        ),
        context=context,
    )
    assert not service.renew(handle, lease_seconds=30, context=context)


def test_unknown_patch_receipt_keeps_unknown_error_and_does_not_publish(
    setup, monkeypatch
):
    service, records, _, request, context, _, _ = setup
    _, handle = started(setup)
    original = type(records).patch

    def unknown(store, dataset, key, patch, **kwargs):
        if dataset == JOBS and patch.set_values.get("status") == "completed":
            return WriteReceipt("unknown", True, outcome=WriteOutcome.UNKNOWN)
        return original(store, dataset, key, patch, **kwargs)

    monkeypatch.setattr(type(records), "patch", unknown)
    with pytest.raises(OutcomeUnknown):
        service.complete(handle, chunk_count=1, context=context)
    assert not service.is_visible(request, handle["attempt_id"], context=context)


def test_same_version_reprocess_clears_visibility_before_replacing_physical_keys(setup):
    service, _, _, request, context, _, _ = setup
    _, first = started(setup)
    assert service.complete(first, chunk_count=1, context=context)
    state = service.submit(
        request.model_copy(update={"idempotency_key": "reprocess"}), context=context
    )
    assert service.is_visible(request, first["attempt_id"], context=context)
    replacement = service.claim(
        lookup(state), owner_id="new", lease_seconds=30, context=context
    )
    assert service.begin_execution(replacement, context=context)
    assert not service.is_visible(request, first["attempt_id"], context=context)
    assert service.complete(replacement, chunk_count=1, context=context)
    assert service.is_visible(request, replacement["attempt_id"], context=context)


def test_unstarted_job_cannot_publish_and_authorization_failure_has_no_state(setup):
    service, records, _, request, context, _, authorize = setup
    authorize.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        service.submit(request, context=context)
    from nexent.storage.models import RecordQuery

    assert records.count(JOBS, RecordQuery(), context=context) == 0
    assert records.count(FILES, RecordQuery(), context=context) == 0
    authorize.side_effect = None
    state = service.submit(request, context=context)
    handle = service.claim(
        lookup(state), owner_id="one", lease_seconds=30, context=context
    )
    assert not service.complete(handle, chunk_count=1, context=context)


def test_delete_before_upload_still_prevents_late_publication(setup):
    service, _, _, request, context, _, _ = setup
    deleted = service.submit(
        KnowledgeFileDelete(
            knowledge_id=1,
            file_id=request.file_id,
            file_version=1,
            idempotency_key="delete-first",
        ),
        context=context,
    )
    assert service.cleanup_ready(lookup(deleted), context=context)
    with pytest.raises(Conflict):
        service.submit(request, context=context)
    newer = request.model_copy(update={"file_version": 2})
    assert service.submit(newer, context=context).status == "queued"
