# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-FILE-ACCESS-01/02: actual scoped admission and current source grants."""

import pytest
from contracts.agentos_knowledge import (
    FileCleanseLookup,
    FileCleanseRequest,
    ObjectReference,
)
from management.services.file.run_cleanse_service import FileCleanseService
from nexent.storage.errors import Conflict, NotFound, ScopeDenied
from nexent.storage.models import PageRequest, RecordQuery

from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_cleanse_service import admission  # noqa: F401


def request(key="attachments/user-a/source.txt", *, run_id="a" * 32, filename="source.txt"):
    return FileCleanseRequest(
        run_id=run_id, filename=filename, idempotency_key="extract-1",
        source=ObjectReference(space="files", key=key, version="etag:pinned", sha256="b" * 64),
    )


def lookup(state, *, run_id=None):
    return FileCleanseLookup(run_id=run_id or state.run_id, job_id=state.job_id)


@pytest.fixture
def api(admission, mocker):  # noqa: F811
    existing, update, closed = admission
    api = FileCleanseService(parser_version="parser-v1")
    mocker.patch.object(api, "_ports", side_effect=existing._ports)
    return api, update, closed


@pytest.mark.parametrize("key", [
    "attachments/user-a/source.txt", "skill-files/user-a/source.txt",
    "workspace/user-a/" + "a" * 32 + "/outputs/source.txt",
])
def test_scoped_sources_submit_inspect_cancel_and_duplicate_are_durable(api, key):
    service, _, closed = api
    args = {"tenant_id": "tenant-a", "user_id": "user-a", "context": context()}
    state = service.submit(request(key), **args)
    assert state.status == "queued" and state.artifact is None
    assert service.submit(request(key), **args) == state
    assert service.inspect(lookup(state), **args) == state
    assert service.cancel(lookup(state), **args).status == "cancelled"
    assert service.cancel(lookup(state), **args).status == "cancelled"
    assert len(closed) == 5


@pytest.mark.parametrize("key", [
    "attachments/user-b/source.txt", "attachments/user-a-evil/source.txt",
    "knowledge_base/shared/source.txt", "images_in_attachments/source.txt", "source.txt",
    "workspace/user-a/" + "c" * 32 + "/outputs/source.txt",
    "workspace/user-b/" + "a" * 32 + "/outputs/source.txt",
])
def test_ungranted_sources_are_rejected_before_reservation(api, key):
    service, _, _ = api
    args = {"tenant_id": "tenant-a", "user_id": "user-a", "context": context()}
    with pytest.raises(ScopeDenied):
        service.submit(request(key), **args)
    # Reuse the identical key with a permitted source; a failed request reserved nothing.
    assert service.submit(request(), **args).status == "queued"


@pytest.mark.parametrize("filename", ["../source.txt", "dir/source.txt", "dir\\source.txt", ".", ".."])
def test_filename_must_be_a_basename(api, filename):
    service, _, _ = api
    with pytest.raises(ScopeDenied):
        service.submit(request(filename=filename), tenant_id="tenant-a", user_id="user-a", context=context())


@pytest.mark.parametrize("operation", ["submit", "inspect", "cancel"])
@pytest.mark.parametrize("revoked", ["cleanse_memberships", "cleanse_accounts"])
def test_revoked_identity_is_checked_for_each_operation(api, operation, revoked):
    service, update, _ = api
    args = {"tenant_id": "tenant-a", "user_id": "user-a", "context": context()}
    state = service.submit(request(), **args)
    update(revoked, delete_flag="Y")
    with pytest.raises(ScopeDenied):
        getattr(service, operation)(request() if operation == "submit" else lookup(state), **args)


@pytest.mark.parametrize("user,tenant", [("user-b", "tenant-a"), ("user-a", "tenant-b")])
def test_other_actor_cannot_inspect_or_cancel(api, user, tenant):
    service, _, _ = api
    state = service.submit(request(), tenant_id="tenant-a", user_id="user-a", context=context())
    for operation in ("inspect", "cancel"):
        with pytest.raises((ScopeDenied, NotFound)):
            getattr(service, operation)(lookup(state), tenant_id=tenant, user_id=user, context=context())


def test_same_actor_cannot_cross_run_or_change_an_idempotent_request(api):
    service, _, _ = api
    args = {"tenant_id": "tenant-a", "user_id": "user-a", "context": context()}
    state = service.submit(request(), **args)
    for operation in ("inspect", "cancel"):
        with pytest.raises(NotFound):
            getattr(service, operation)(lookup(state, run_id="c" * 32), **args)
    with pytest.raises(Conflict):
        service.submit(request(filename="changed.txt"), **args)
    other = service.submit(request(run_id="c" * 32), **args)
    assert other.job_id != state.job_id


def test_production_ports_do_not_grant_knowledge_or_file_catalogs(admission, resources, mocker):  # noqa: F811
    _, _, engine, _ = resources
    mocker.patch("infrastructure.knowledge_cleanse.record_engine", return_value=engine)
    service = FileCleanseService(parser_version="parser-v1")
    with service._ports("tenant-a", "user-a", context=context()) as (jobs, authority):
        assert authority.scope.namespaces == {"cleanse_memberships", "cleanse_accounts"}
        assert jobs.scope.actor_id == "user-a" and jobs.scope.tenant_id == "tenant-a"
        with pytest.raises(ScopeDenied):
            authority.query("cleanse_knowledge", RecordQuery(), PageRequest(), context=context())
