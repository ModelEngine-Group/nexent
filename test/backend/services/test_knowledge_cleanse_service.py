# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB admission joins live DAC and durable job policy through owned ports."""

from contextlib import contextmanager

import pytest
from contracts.knowledge_cleanse import KnowledgeCleanseLookup
from management.services.file import knowledge_cleanse_service as service
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import PageRequest, Revision, StorageScope

from infrastructure.rdb.cleanse_jobs import DATASET, bind_cleanse_jobs, cleanse_jobs
from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context, request
from test.backend.services.test_knowledge_cleanse_jobs import knowledge_request


@pytest.fixture
def admission(resources, monkeypatch):  # noqa: F811 - Imported shared pytest fixture.
    _, update, engine, _ = resources
    engine.update_execution_options(schema_translate_map={"nexent": None})
    cleanse_jobs.create(engine)
    closed = []

    def claim(store, dataset, query, patch, *, limit, context):
        # SQLite substitutes only the PostgreSQL lock, retaining actual query/CAS.
        rows = store.query(
            dataset, query, PageRequest(limit=limit), context=context
        ).items
        for row in rows:
            store.patch(
                dataset,
                row["id"],
                patch,
                expected=Revision(str(row["revision"])),
                context=context,
            )
        return rows

    monkeypatch.setattr("infrastructure.rdb.record_queries.claim_records", claim)

    @contextmanager
    def ports(tenant_id, user_id, *, context):
        jobs = bind_cleanse_jobs(
            StorageScope("management", tenant_id, user_id, {DATASET}), engine
        )
        resources = bind_cleanse_resources(
            StorageScope("management", tenant_id, user_id, set(TABLES)), engine
        )
        try:
            yield jobs, resources
        finally:
            resources.close()
            jobs.close()
            closed.append(True)

    monkeypatch.setattr(service, "knowledge_cleanse_ports", ports)
    return service.KnowledgeCleanseService(parser_version="parser-v1"), update, closed


def lookup(state):
    return KnowledgeCleanseLookup(
        knowledge_id=state.knowledge_id,
        file_id=state.file_id,
        file_version=state.file_version,
        job_id=state.job_id,
    )


def test_admission_replay_inspect_and_cancel_use_live_authorization(admission):
    api, _, closed = admission
    args = {"tenant_id": "tenant-a", "user_id": "user-a", "context": context()}
    state = api.submit(knowledge_request(), **args)
    assert state.status == "queued"
    assert api.submit(knowledge_request(), **args).job_id == state.job_id
    assert api.inspect(lookup(state), **args) == state
    assert api.cancel(lookup(state), **args).status == "cancelled"
    assert api.cancel(lookup(state), **args).status == "cancelled"
    assert len(closed) == 5


@pytest.mark.parametrize("operation", ["submit", "inspect", "cancel"])
def test_revoked_account_cannot_use_any_public_operation(admission, operation):
    api, update, closed = admission
    args = {"tenant_id": "tenant-a", "user_id": "user-a", "context": context()}
    state = api.submit(knowledge_request(), **args)
    update("cleanse_accounts", user_roles=[])
    value = knowledge_request() if operation == "submit" else lookup(state)
    with pytest.raises(ScopeDenied):
        getattr(api, operation)(value, **args)
    assert len(closed) == 2
    update("cleanse_accounts", user_roles=["DEV"])
    assert api.inspect(lookup(state), **args) == state


@pytest.mark.parametrize(
    "tenant,user", [("tenant-b", "user-a"), ("tenant-a", "user-b")]
)
def test_other_tenant_or_user_cannot_inspect(admission, tenant, user):
    api, _, _ = admission
    state = api.submit(
        knowledge_request(), tenant_id="tenant-a", user_id="user-a", context=context()
    )
    with pytest.raises(ScopeDenied):
        api.inspect(lookup(state), tenant_id=tenant, user_id=user, context=context())


def test_stale_source_rejected_and_ports_closed(admission):
    api, update, closed = admission
    update("cleanse_files", source_generation=1)
    with pytest.raises(ScopeDenied):
        api.submit(
            knowledge_request(),
            tenant_id="tenant-a",
            user_id="user-a",
            context=context(),
        )
    assert closed == [True]


def test_run_scope_rejected_before_ports_open(admission):
    api, _, closed = admission
    with pytest.raises(ScopeDenied):
        api.submit(request(), tenant_id="tenant-a", user_id="user-a", context=context())
    assert closed == []


@pytest.mark.parametrize("user", ["", " " * 5, "a" * 101, None])
def test_invalid_identity_does_not_open_ports(admission, user):
    api, _, closed = admission
    with pytest.raises(ScopeDenied):
        api.submit(
            knowledge_request(), tenant_id="tenant-a", user_id=user, context=context()
        )
    assert closed == []


def test_expired_deadline_does_not_open_ports(admission):
    from dataclasses import replace

    api, _, closed = admission
    with pytest.raises(DeadlineExceeded):
        api.submit(
            knowledge_request(),
            tenant_id="tenant-a",
            user_id="user-a",
            context=replace(context(), deadline=0),
        )
    assert closed == []
