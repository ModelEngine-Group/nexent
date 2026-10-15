# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deletion previews validate inputs and query bindings without probing KBs."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import apps.knowledge_reference_app as routes
import database.knowledge_reference_db as reference_db
import services.knowledge_reference_service as service
from consts.const import ASSET_OWNER_TENANT_ID
from consts.model import KnowledgeReferencePreviewRequest
from middleware.exception_handler import ExceptionHandlerMiddleware


@pytest.mark.parametrize("payload", [
    {}, {"provider": "local"}, {"resource_id": "idx-1"},
    {"provider": "other", "resource_id": "idx-1"},
    {"provider": "LOCAL", "resource_id": "idx-1"},
    {"provider": "aidp", "resource_id": ""},
    {"provider": "aidp", "resource_id": "   "},
])
def test_preview_model_rejects_invalid_inputs(payload):
    with pytest.raises(ValidationError):
        KnowledgeReferencePreviewRequest(**payload)


def test_preview_model_trims_resource_id():
    request = KnowledgeReferencePreviewRequest(provider="aidp", resource_id=" kds-1 ")
    assert request.resource_id == "kds-1"


@pytest.fixture()
def preview_client(monkeypatch):
    monkeypatch.setattr(routes, "get_current_user_id", lambda auth: ("u1", "t1"))
    collect = MagicMock(return_value={"agents": [], "hidden_agent_count": 0, "total_agent_count": 0})
    monkeypatch.setattr(routes, "collect_agent_reference_preview", collect)

    async def run(task_name, function, *args, lane, owner, **kwargs):
        assert lane == "control-io"
        return function(*args, **kwargs)

    worker = AsyncMock(side_effect=run)
    monkeypatch.setattr(routes, "run_blocking", worker, raising=False)
    monkeypatch.setattr(
        routes, "resolve_item_statuses", MagicMock(side_effect=AssertionError("KB probe")), raising=False,
    )
    app = FastAPI()
    app.add_middleware(ExceptionHandlerMiddleware)
    app.include_router(routes.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, collect, worker


def test_status_endpoint_is_removed(preview_client):
    client, _, _ = preview_client
    assert client.post("/knowledge-bases/statuses", json={"items": []}).status_code == 404


@pytest.mark.parametrize("provider", ["local", "aidp"])
def test_preview_queries_bindings_without_knowledge_status_checks(preview_client, provider):
    client, collect, worker = preview_client
    response = client.post("/knowledge-bases/reference-preview", json={
        "provider": provider, "resource_id": " missing-resource ",
    })
    assert response.status_code == 200
    assert response.json() == {"agents": [], "hidden_agent_count": 0, "total_agent_count": 0}
    collect.assert_called_once_with([(provider, "missing-resource")], user_id="u1", tenant_id="t1")
    worker.assert_awaited_once()


def test_invalid_preview_input_never_reaches_service(preview_client):
    client, collect, worker = preview_client
    response = client.post("/knowledge-bases/reference-preview", json={"provider": "local", "resource_id": " "})
    assert response.status_code == 422
    collect.assert_not_called()
    worker.assert_not_awaited()


def test_preview_does_not_hide_database_errors_as_an_empty_result(preview_client):
    client, collect, _ = preview_client
    collect.side_effect = RuntimeError("database unavailable")
    response = client.post("/knowledge-bases/reference-preview", json={"provider": "local", "resource_id": "idx-1"})
    assert response.status_code == 500


def test_preview_without_references_does_not_lookup_knowledge(monkeypatch):
    @contextmanager
    def session():
        yield object()

    monkeypatch.setattr(service, "get_db_session", session)
    monkeypatch.setattr(service, "query_live_agent_reference_rows", lambda *args: [])
    context = MagicMock(side_effect=AssertionError("no agent metadata needed"))
    monkeypatch.setattr(service, "build_visibility_context", context)
    assert service.collect_agent_reference_preview(
        [("aidp", "missing-kds")], user_id="u1", tenant_id="t1",
    ) == {"agents": [], "hidden_agent_count": 0, "total_agent_count": 0}
    context.assert_not_called()


def test_preview_metadata_query_is_scoped_to_current_tenant_and_shared_assets():
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value.all.return_value = []
    reference_db.query_agent_reference_metadata(session, [1, 2], tenant_id="t1")
    predicates = query.filter.call_args.args
    tenant_predicate = next(item for item in predicates if str(item.left).endswith(".tenant_id"))
    assert set(tenant_predicate.right.value) == {"t1", ASSET_OWNER_TENANT_ID}
    session.commit.assert_not_called()
