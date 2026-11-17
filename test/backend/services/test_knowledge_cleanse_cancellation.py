# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-CLEANSE-DRAIN-02: resource DAC with real SI job cancellation."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from contracts.agentos_knowledge import KnowledgeFileReference
from contracts.knowledge_deletion import KnowledgeDeletionIntent
from management.services.file.cleanse_cancellation import cancel_knowledge_executions
from management.services.file.knowledge_cleanse_service import KnowledgeCleanseService
from nexent.storage.errors import NotFound, ScopeDenied
from nexent.storage.models import PageRequest, RecordQuery, StorageScope

from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context, request
from test.backend.services.test_cleanse_jobs import setup as setup  # noqa: PLC0414
from test.backend.services.test_knowledge_cleanse_jobs import knowledge_request, lookup


@pytest.fixture
def prepared(setup, resources, monkeypatch):
    make, _ = setup
    _, update, engine, tables = resources
    with engine.begin() as connection:
        for name, values in [
            ("cleanse_memberships", {"user_tenant_id": 2, "tenant_id": "tenant-a", "user_id": "user-b", "delete_flag": "N"}),
            ("cleanse_accounts", {"account_id": 2, "tenant_id": "tenant-a", "user_id": "user-b", "user_roles": ["DEV"], "delete_flag": "N"}),
            ("cleanse_group_memberships", {"group_user_id": 2, "tenant_id": "tenant-a", "user_id": "user-b", "group_id": 10, "delete_flag": "N"}),
        ]:
            connection.execute(tables[name].insert(), values)
    value = KnowledgeDeletionIntent(knowledge_id=1, file_id="b" * 32, file_version=0,
                                   user_id="user-b", scope="full", index_name="kb-one", filename="source.txt",
                                   source=knowledge_request().source)
    update("cleanse_files", status="DELETE_REQUESTED", deletion_request=value.model_dump(mode="json"))
    service = KnowledgeCleanseService(parser_version="parser-v1")

    @contextmanager
    def ports(tenant, user, *, context):
        jobs = make(user, tenant).records
        authority = bind_cleanse_resources(StorageScope("management", tenant, user, set(TABLES)), engine)
        try:
            yield jobs, authority
        finally:
            authority.close()
            jobs.close()

    monkeypatch.setattr(service, "_ports", ports)
    reference = KnowledgeFileReference(knowledge_id=1, file_id="b" * 32, file_version=0)
    return SimpleNamespace(make=make, update=update, service=service, reference=reference)


def cancel(p, **changes):
    tenant, user = changes.get('tenant_id', 'tenant-a'), changes.get('user_id', 'user-b')
    with p.service._records(tenant, user, context()) as (jobs, resources):
        return cancel_knowledge_executions(jobs, resources, p.reference, user_id=user, context=context())


def test_current_group_editor_cancels_other_uploaders_resource_without_private_task_access(prepared):
    p = prepared
    public = p.make()
    state = public.submit(knowledge_request(), context=context())
    with pytest.raises(NotFound):
        p.make("user-b").inspect(lookup(state), context=context())
    result = cancel(p)
    assert result == {"task_ids": [state.job_id], "cancelled_count": 1, "execution_drained": True}
    row = public.record(lookup(state), context=context())
    assert row["user_id"] == "user-a" and row["updated_by"] == "user-b"
    assert row["status"] == "cancelled"


def test_running_process_must_confirm_end_even_after_resource_cancel(prepared):
    p = prepared
    public, worker = p.make(), p.make("worker")
    state = public.submit(knowledge_request(), context=context())
    handle = worker.claim("worker", lease_seconds=60, context=context())
    worker.begin_execution(handle, context=context())
    assert cancel(p)["execution_drained"] is False
    assert public.inspect(lookup(state), context=context()).status == "cancelled"
    worker.finish_execution(handle, context=context())
    assert cancel(p)["execution_drained"] is True
    assert public.record(lookup(state), context=context())["reconcile_required"] is True


@pytest.mark.parametrize("values", [{"deletion_request": None}, {"status": "COMPLETED"}])
def test_missing_persistent_full_fence_cannot_cancel_jobs(prepared, values):
    p = prepared
    public = p.make()
    state = public.submit(knowledge_request(), context=context())
    p.update("cleanse_files", **values)
    with pytest.raises(ScopeDenied):
        cancel(p)
    assert public.inspect(lookup(state), context=context()).status == "queued"


def test_revoked_editor_cannot_cancel_or_claim_drained(prepared):
    p = prepared
    public = p.make()
    state = public.submit(knowledge_request(), context=context())
    p.update("cleanse_group_memberships", delete_flag="Y")
    with pytest.raises(ScopeDenied):
        cancel(p)
    assert public.inspect(lookup(state), context=context()).status == "queued"


def test_other_scope_file_and_newer_generation_remain_queued(prepared):
    p = prepared
    public = p.make()
    covered = public.submit(knowledge_request(), context=context())
    untouched = [public.submit(value, context=context()) for value in (
        request(), knowledge_request(file_id="c" * 32), knowledge_request(file_version=1),
    )]
    result = cancel(p)
    assert result["task_ids"] == [covered.job_id]
    for state in untouched:
        raw = public.records.query("file_cleanse_jobs", RecordQuery(),
                                   PageRequest(limit=100), context=context())
        assert next(row for row in raw.items if row["job_id"] == state.job_id)["status"] == "queued"


def test_no_jobs_is_drained_only_after_current_resource_fence_is_verified(prepared):
    assert cancel(prepared) == {"task_ids": [], "cancelled_count": 0, "execution_drained": True}
    prepared.update("cleanse_files", deletion_request=None)
    with pytest.raises(ScopeDenied):
        cancel(prepared)



def test_cancellation_consumes_every_page(prepared):
    p = prepared
    public = p.make()
    expected = {public.submit(knowledge_request(idempotency_key=f"job-{i}"), context=context()).job_id for i in range(101)}
    result = cancel(p)
    assert set(result["task_ids"]) == expected
    assert result["cancelled_count"] == 101 and result["execution_drained"] is True


def test_legacy_unknown_execution_end_is_never_backfilled_by_cancellation(prepared):
    from nexent.storage.models import FieldPatch

    p = prepared
    public = p.make()
    state = public.submit(knowledge_request(), context=context())
    public.cancel(lookup(state), context=context())
    row = public.record(lookup(state), context=context())
    public.records.patch("file_cleanse_jobs", row["id"], FieldPatch(set_values={"execution_ended": None}), context=context())
    assert cancel(p)["execution_drained"] is False



@pytest.mark.parametrize("permission", ["READ", "PRIVATE"])
def test_current_read_only_or_private_group_permission_cannot_cancel(prepared, permission):
    p = prepared
    public = p.make()
    state = public.submit(knowledge_request(), context=context())
    p.update("cleanse_knowledge", ingroup_permission=permission)
    with pytest.raises(ScopeDenied):
        cancel(p)
    assert public.inspect(lookup(state), context=context()).status == "queued"


def test_cancellation_cannot_cross_the_authenticated_tenant(prepared):
    p = prepared
    public = p.make()
    state = public.submit(knowledge_request(), context=context())
    with pytest.raises(ScopeDenied):
        cancel(p, user_id='user-b', tenant_id='tenant-b')
    assert public.inspect(lookup(state), context=context()).status == "queued"
