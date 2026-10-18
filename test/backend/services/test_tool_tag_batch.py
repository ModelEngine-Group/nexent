# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps import tag_management_app
from consts.exceptions import ValidationError as DomainValidationError
from consts.model import ToolTagAssignmentBatchRequest
from database.tag_management_db import TagManagementDB
from database.tool_db import query_tenant_tools_by_ids
from services.tag_management_service import TagManagementService
from services.tag_resource_adapters import AuthenticatedCaller


@pytest.mark.parametrize("ids", [[], [0], [-1], [2**63], list(range(1, 502))])
def test_request_rejects_invalid_or_unbounded_ids(ids):
    with pytest.raises(ValidationError):
        ToolTagAssignmentBatchRequest(tool_ids=ids)


def test_request_deduplicates_and_rejects_tenant_override():
    assert ToolTagAssignmentBatchRequest(tool_ids=[2, 1, 2]).tool_ids == [2, 1]
    with pytest.raises(ValidationError):
        ToolTagAssignmentBatchRequest(tool_ids=[1], tenant_id="other")


def test_http_batch_route_validates_body_and_accepts_frontend_string_ids(monkeypatch):
    app = FastAPI()
    app.include_router(tag_management_app.router)
    caller = AuthenticatedCaller("reader", "tenant-a", role="USER")
    monkeypatch.setattr(tag_management_app, "_assignment_caller", lambda _: caller)
    service = MagicMock(return_value=[])
    monkeypatch.setattr(TagManagementService, "get_tool_assignments_batch", service)
    with TestClient(app) as client:
        response = client.post("/tag-libraries/assignments/tool/batch_read", json={"tool_ids": ["1", "2", "1"]})
        assert response.status_code == 200
        assert response.json() == []
        service.assert_called_once_with(caller, [1, 2])
        for payload in [{"tool_ids": []}, {"tool_ids": [0]}, {"tool_ids": [1], "tenant_id": "other"}]:
            assert client.post("/tag-libraries/assignments/tool/batch_read", json=payload).status_code == 422
        service.assert_called_once()


def test_batch_service_uses_two_bulk_calls_and_omits_invisible_ids(monkeypatch):
    tools = MagicMock(return_value=[{"tool_id": 2}, {"tool_id": 1}])
    assignments = MagicMock(return_value={"2": [{"value_id": 7}], "1": []})
    monkeypatch.setattr("services.tag_management_service.query_tenant_tools_by_ids", tools)
    monkeypatch.setattr(TagManagementDB, "list_resource_assignments_batch", assignments)
    monkeypatch.setattr(
        TagManagementDB, "list_resource_assignments",
        MagicMock(side_effect=AssertionError("per-tool reads are forbidden")),
    )
    caller = AuthenticatedCaller("reader", "tenant-a", role="USER")
    result = TagManagementService.get_tool_assignments_batch(caller, [2, 99, 1, 2])
    tools.assert_called_once_with("tenant-a", [2, 99, 1])
    assignments.assert_called_once_with("tenant-a", "tool", ["2", "1"], "default_resource")
    assert [item["resource_id"] for item in result] == ["2", "1"]
    assert [item["assignment_count"] for item in result] == [1, 0]
    assert result[1]["assignments"] == []


def test_empty_batch_avoids_database(monkeypatch):
    tools = MagicMock()
    monkeypatch.setattr("services.tag_management_service.query_tenant_tools_by_ids", tools)
    assert TagManagementService.get_tool_assignments_batch(AuthenticatedCaller("u", "t"), []) == []
    tools.assert_not_called()


def test_tool_lookup_uses_one_tenant_scoped_in_query(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.all.return_value = []
    context = MagicMock()
    context.__enter__.return_value = session
    monkeypatch.setattr("database.tool_db.get_db_session", lambda: context)
    assert query_tenant_tools_by_ids("tenant-a", [1, 2]) == []
    session.query.assert_called_once()
    query.all.assert_called_once()
    criteria = {criterion.left.key: criterion.right.value for criterion in query.filter.call_args.args}
    assert criteria == {"author": "tenant-a", "delete_flag": "Y", "tool_id": [1, 2]}


def test_assignment_batch_uses_one_query_and_preserves_empty_resources(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.join.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    definition = SimpleNamespace(
        definition_id=4, definition_key="department", definition_name="Department", selection_mode="multi_select"
    )
    value = SimpleNamespace(value_id=8, display_value="Finance", status="active")
    query.all.return_value = [(SimpleNamespace(resource_id="2"), definition, value)]
    context = MagicMock()
    context.__enter__.return_value = session
    monkeypatch.setattr("database.tag_management_db.get_db_session", lambda: context)
    binding = MagicMock()
    monkeypatch.setattr(TagManagementDB, "_get_active_resource_binding", binding)
    result = TagManagementDB.list_resource_assignments_batch("tenant-a", "tool", ["1", "2"], "default_resource")
    assert result["1"] == []
    assert result["2"][0]["display_value"] == "Finance"
    session.query.assert_called_once()
    query.all.assert_called_once()
    binding.assert_called_once_with(session, "tenant-a", "tool", "default_resource", for_update=False)
    criteria = {criterion.left.key: criterion.right.value for criterion in query.filter.call_args.args}
    assert criteria == {"tenant_id": "tenant-a", "resource_type": "tool", "resource_id": ["1", "2"], "delete_flag": "N"}


def test_batch_route_forwards_server_identity_and_maps_errors(monkeypatch):
    monkeypatch.setattr(tag_management_app, "get_current_user_context", lambda _: ("reader", "tenant-a", "USER"))
    service = MagicMock(return_value=[])
    monkeypatch.setattr(TagManagementService, "get_tool_assignments_batch", service)
    request = ToolTagAssignmentBatchRequest(tool_ids=[1, 2])
    assert tag_management_app.get_tool_tag_assignments_batch(request, "Bearer token") == []
    caller, ids = service.call_args.args
    assert (caller.authenticated_tenant_id, caller.role, ids) == ("tenant-a", "USER", [1, 2])
    service.side_effect = DomainValidationError("inactive binding")
    with pytest.raises(HTTPException) as error:
        tag_management_app.get_tool_tag_assignments_batch(request, "Bearer token")
    assert error.value.status_code == 400
