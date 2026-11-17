# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Confirmed ingestion progress is owner-fenced, monotonic and exposed through AgentOS."""

import pytest
from contracts.agentos_knowledge import KnowledgeFileDelete, KnowledgeJobState
from nexent.storage.errors import Conflict, InvalidInput, NotFound
from nexent.storage.models import StorageScope
from pydantic import ValidationError
from runtime.knowledge_base.jobs import KnowledgeJobs

from infrastructure.rdb.knowledge_jobs import FILES, JOBS, bind_knowledge_jobs
from test.backend.services.test_knowledge_jobs import lookup, setup  # noqa: F401


def running(s):
    service, _, _, request, context, _, _ = s
    state = service.submit(request, context=context)
    handle = service.claim(
        lookup(state), owner_id="owner", lease_seconds=30, context=context
    )
    assert service.begin_execution(handle, context=context)
    return service, state, handle, request, context


def test_progress_is_monotonic_idempotent_and_completion_is_confirmed(setup):  # noqa: F811
    service, state, handle, _, context = running(setup)
    assert service.progress(handle, processed_chunks=0, total_chunks=3, context=context)
    assert service.progress(handle, processed_chunks=1, total_chunks=3, context=context)
    assert service.progress(handle, processed_chunks=1, total_chunks=3, context=context)
    observed = service.inspect(lookup(state), context=context)
    assert (observed.processed_chunks, observed.total_chunks) == (1, 3)
    with pytest.raises(Conflict):
        service.progress(handle, processed_chunks=0, total_chunks=3, context=context)
    with pytest.raises(Conflict):
        service.progress(handle, processed_chunks=1, total_chunks=4, context=context)
    with pytest.raises(Conflict):
        service.complete(handle, chunk_count=2, context=context)
    assert service.progress(handle, processed_chunks=3, total_chunks=3, context=context)
    assert service.inspect(lookup(state), context=context).status == "running"
    assert not service.is_visible(lookup(state), handle["attempt_id"], context=context)
    assert service.complete(handle, chunk_count=3, context=context)
    final = service.inspect(lookup(state), context=context)
    assert final.status == "completed" and (
        final.processed_chunks,
        final.total_chunks,
    ) == (3, 3)


def test_deleted_attempt_cannot_publish_more_progress(setup):  # noqa: F811
    service, state, handle, request, context = running(setup)
    assert service.progress(handle, processed_chunks=1, total_chunks=3, context=context)
    service.submit(
        KnowledgeFileDelete(
            knowledge_id=request.knowledge_id,
            file_id=request.file_id,
            file_version=request.file_version,
            idempotency_key="delete",
        ),
        context=context,
    )
    assert not service.progress(
        handle, processed_chunks=2, total_chunks=3, context=context
    )
    current = service.inspect(lookup(state), context=context)
    assert current.status == "cancelled" and current.processed_chunks == 1


@pytest.mark.parametrize(
    "processed,total", [(-1, 3), (True, 3), (4, 3), (0, -1), (0, 2**31)]
)
def test_invalid_progress_is_rejected_before_writing(setup, processed, total):  # noqa: F811
    service, state, handle, _, context = running(setup)
    with pytest.raises(InvalidInput):
        service.progress(
            handle, processed_chunks=processed, total_chunks=total, context=context
        )
    assert service.inspect(lookup(state), context=context).processed_chunks is None


def test_transport_rejects_invalid_counter_pairs():
    values = {
        "knowledge_id": 1,
        "file_id": "a" * 32,
        "file_version": 0,
        "job_id": "b" * 32,
        "status": "running",
    }
    assert KnowledgeJobState(**values).processed_chunks is None
    for processed, total in [(True, 3), (-1, 3), (4, 3)]:
        with pytest.raises(ValidationError):
            KnowledgeJobState(**values, processed_chunks=processed, total_chunks=total)


@pytest.mark.parametrize("expired", [False, True])
def test_wrong_or_expired_attempt_cannot_write_progress(setup, expired):  # noqa: F811
    service, state, handle, _, context = running(setup)
    assert service.progress(handle, processed_chunks=1, total_chunks=3, context=context)
    if expired:
        from datetime import timedelta

        setup[5][0] += timedelta(seconds=60)
    else:
        handle = {**handle, "attempt_id": "f" * 32}
    assert not service.progress(
        handle, processed_chunks=2, total_chunks=3, context=context
    )
    assert service.inspect(lookup(state), context=context).processed_chunks == 1


def test_other_user_in_same_tenant_cannot_update_or_inspect_progress(setup):  # noqa: F811
    service, state, handle, _, context = running(setup)
    assert service.progress(handle, processed_chunks=1, total_chunks=3, context=context)
    records = bind_knowledge_jobs(
        StorageScope("runtime", "tenant", "intruder", {FILES, JOBS}), setup[2]
    )
    other = KnowledgeJobs(records, authorize=lambda *args, **kwargs: None)
    try:
        with pytest.raises(NotFound):
            other.progress(handle, processed_chunks=2, total_chunks=3, context=context)
        with pytest.raises(NotFound):
            other.inspect(lookup(state), context=context)
        assert service.inspect(lookup(state), context=context).processed_chunks == 1
    finally:
        records.close()
