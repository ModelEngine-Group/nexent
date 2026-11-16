# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Durable job policy with SQL records and a controlled single-thread claim boundary."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from contracts.agentos_knowledge import (
    FileCleanseLookup,
    FileCleanseRequest,
    ObjectReference,
)
from management.services.file.cleanse_jobs import CleanseJobs
from nexent.storage.errors import Conflict, NotFound
from nexent.storage.models import PageRequest, RecordQuery, Revision, StorageScope

from infrastructure.rdb.cleanse_jobs import DATASET, bind_cleanse_jobs, cleanse_jobs
from test.backend.infrastructure.test_record_store import context


@pytest.fixture
def setup(monkeypatch):
    engine = sa.create_engine(
        "sqlite://", execution_options={"schema_translate_map": {"nexent": None}}
    )
    cleanse_jobs.create(engine)
    now = [datetime(2026, 11, 16, tzinfo=timezone.utc)]

    def claim(store, dataset, query, patch, *, limit, context):
        # Only substitute the external lock boundary; real job/query/CAS logic remains active.
        assert store._connection is not None
        rows = store.query(
            dataset, query, PageRequest(limit=limit), context=context
        ).items
        result = []
        for row in rows:
            receipt = store.patch(
                dataset,
                row["id"],
                patch,
                expected=Revision(str(row["revision"])),
                context=context,
            )
            assert receipt.matched
            result.append(
                store.get(dataset, row["id"], fields=query.fields, context=context)
            )
        return tuple(result)

    monkeypatch.setattr("infrastructure.rdb.record_queries.claim_records", claim)

    def make(user="user-a", tenant="tenant-a", authorize=None):
        records = bind_cleanse_jobs(
            StorageScope("management", tenant, user, {DATASET}), engine
        )
        return CleanseJobs(
            records,
            authorize=authorize or Mock(),
            parser_version="parser-v1",
            clock=lambda: now[0],
        )

    yield make, now
    engine.dispose()


def request():
    return FileCleanseRequest(
        run_id="a" * 32,
        source=ObjectReference(
            space="files", key="source.txt", version="etag:source", sha256="1" * 64
        ),
        filename="source.txt",
        idempotency_key="request-1",
    )


def lookup(state):
    return FileCleanseLookup(job_id=state.job_id, run_id=state.run_id)


def artifact():
    return ObjectReference(
        space="files", key="artifact.json", version="etag:artifact", sha256="2" * 64
    )


def test_admission_replay_survives_service_recreation(setup):
    make, _ = setup
    jobs = make()
    first = jobs.submit(request(), context=context())
    assert first.status == "queued"
    assert make().submit(request(), context=context()).job_id == first.job_id
    assert jobs.records.count(DATASET, RecordQuery(), context=context()) == 1
    changed = request().model_copy(update={"filename": "changed.txt"})
    with pytest.raises(Conflict):
        jobs.submit(changed, context=context())


def test_lost_admission_response_reuses_committed_job(setup, mocker):
    from nexent.storage.errors import OutcomeUnknown

    make, _ = setup
    jobs = make()
    original = jobs.records.create

    def committed_then_lost(*args, **kwargs):
        original(*args, **kwargs)
        raise OutcomeUnknown()

    create = mocker.patch.object(
        jobs.records, "create", side_effect=committed_then_lost
    )
    with pytest.raises(OutcomeUnknown):
        jobs.submit(request(), context=context())
    recovered = jobs.submit(request(), context=context())
    assert recovered.status == "queued"
    create.assert_called_once()
    assert jobs.records.count(DATASET, RecordQuery(), context=context()) == 1


@pytest.mark.parametrize(
    "user,tenant,run",
    [
        ("user-b", "tenant-a", "a" * 32),
        ("user-a", "tenant-b", "a" * 32),
        ("user-a", "tenant-a", "b" * 32),
    ],
)
def test_inspect_preserves_user_tenant_and_run_ownership(setup, user, tenant, run):
    make, _ = setup
    state = make().submit(request(), context=context())
    foreign = FileCleanseLookup(job_id=state.job_id, run_id=run)
    with pytest.raises(NotFound):
        make(user, tenant).inspect(foreign, context=context())


def test_authorization_rejects_before_admission(setup):
    make, _ = setup
    jobs = make(authorize=Mock(side_effect=PermissionError("denied")))
    with pytest.raises(PermissionError):
        jobs.submit(request(), context=context())
    assert jobs.records.count(DATASET, RecordQuery(), context=context()) == 0


def test_expired_attempt_cannot_complete_after_takeover(setup):
    make, now = setup
    jobs = make()
    state = jobs.submit(request(), context=context())
    first = jobs.claim("worker-a", lease_seconds=60, context=context())
    assert jobs.claim("worker-b", lease_seconds=60, context=context()) is None
    now[0] += timedelta(seconds=61)
    second = jobs.claim("worker-b", lease_seconds=60, context=context())
    assert first["attempt_id"] != second["attempt_id"]
    assert not jobs.transition(
        first, status="completed", artifact=artifact(), context=context()
    )
    assert jobs.transition(
        second, status="completed", artifact=artifact(), context=context()
    )
    assert jobs.inspect(lookup(state), context=context()).artifact == artifact()


def test_cancel_fences_running_attempt(setup):
    make, _ = setup
    jobs = make()
    state = jobs.submit(request(), context=context())
    handle = jobs.claim("worker", lease_seconds=60, context=context())
    assert jobs.cancel(lookup(state), context=context()).status == "cancelled"
    assert not jobs.transition(
        handle, status="completed", artifact=artifact(), context=context()
    )
    assert jobs.inspect(lookup(state), context=context()).artifact is None


def test_unknown_write_is_not_blindly_retried(setup):
    make, now = setup
    jobs = make()
    state = jobs.submit(request(), context=context())
    handle = jobs.claim("worker", lease_seconds=60, context=context())
    assert jobs.mark_uncertain(handle, context=context())
    now[0] += timedelta(seconds=61)
    assert jobs.claim("next", lease_seconds=60, context=context()) is None
    assert jobs.ready(context=context()) == ()
    retained = jobs.inspect(lookup(state), context=context())
    assert (
        retained.status == "running"
        and retained.error_code == "CLEANSE_OUTCOME_UNKNOWN"
    )


def test_renewal_keeps_attempt_and_extends_lease(setup):
    make, now = setup
    jobs = make()
    jobs.submit(request(), context=context())
    handle = jobs.claim("worker", lease_seconds=60, context=context())
    now[0] += timedelta(seconds=30)
    assert jobs.transition(
        handle, status="running", lease_seconds=60, context=context()
    )
    now[0] += timedelta(seconds=31)
    assert jobs.claim("other", lease_seconds=60, context=context()) is None
