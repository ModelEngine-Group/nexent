# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public file-list adapters retain JSON, actor, and errors without native VDB."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from management.api.knowledge_base import vectordatabase as ordinary
from management.services.knowledge_base import file_listing
from nexent.storage.errors import DeadlineExceeded, ScopeDenied

from backend.http.server.exception_handlers import register_exception_handlers


@pytest.fixture
def public(mocker):
    app = FastAPI()
    app.include_router(ordinary.router)
    register_exception_handlers(app)

    def forbidden():
        raise AssertionError("Native VDB dependency used")

    app.dependency_overrides[ordinary.get_vector_db_core] = forbidden
    mocker.patch.object(
        ordinary, "get_current_user_id", return_value=("reader", "tenant-a")
    )
    query = mocker.patch.object(
        file_listing,
        "list_knowledge_files",
        return_value={"files": [{"path_or_url": "source"}]},
    )
    tags = mocker.patch.object(
        ordinary,
        "project_authorized_document_tags",
        side_effect=lambda files, **kw: [dict(f, tags=[]) for f in files],
    )
    with TestClient(app) as client:
        yield SimpleNamespace(**locals())


def test_public_files_keep_shape_tags_and_actual_actor(public):
    s = public
    result = s.client.get("/indices/kb/files")
    assert result.status_code == 200 and result.json() == {
        "status": "success",
        "files": [{"path_or_url": "source", "tags": []}],
    }
    name, actor = s.query.await_args.args
    assert (name, actor.user_id, actor.tenant_id) == ("kb", "reader", "tenant-a")
    assert s.tags.await_args.kwargs == {"index_name": "kb", "actor": s.query.await_args.args[1]}
    assert s.tags.await_count == 1


@pytest.mark.parametrize(
    "error,status",
    [(ScopeDenied(), 403), (DeadlineExceeded(), 500), (ValueError("broken"), 500)],
)
def test_public_errors_do_not_return_empty_success(public, error, status):
    s = public
    s.query.side_effect = error
    response = s.client.get("/indices/kb/files")
    assert response.status_code == status
    s.tags.assert_not_called()
    assert s.query.await_count == 1


async def test_northbound_service_preserves_actor_without_vdb(mocker):
    from management.services.northbound import list_knowledge_files_for_northbound

    query = mocker.patch.object(
        file_listing, "list_knowledge_files", return_value={"files": [{"file": "one"}]}
    )
    ctx = SimpleNamespace(user_id="publisher", tenant_id="asset-tenant")
    assert (
        await list_knowledge_files_for_northbound(ctx=ctx, index_name="kb")
        == query.return_value
    )
    name, actor = query.await_args.args
    assert (name, actor.user_id, actor.tenant_id) == ("kb", "publisher", "asset-tenant")
