# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps import tag_management_app
from consts.model import AgentTagAssignmentBatchRequest
from database.agent_db import query_agent_info_by_ids
from database.tag_management_db import TagManagementDB
from services.tag_management_service import TagManagementService
from services.tag_resource_adapters import AuthenticatedCaller


@pytest.mark.parametrize("ids", [[], [0], [-1], [2**63], list(range(1, 502))])
def test_agent_batch_rejects_invalid_ids(ids):
    with pytest.raises(ValidationError):
        AgentTagAssignmentBatchRequest(agent_ids=ids)


def test_batch_http_identity_deduplication_and_validation(monkeypatch):
    app = FastAPI()
    app.include_router(tag_management_app.router)
    monkeypatch.setattr(tag_management_app, "get_current_user_context", lambda _: ("reader", "tenant-a", "USER"))
    service = MagicMock(return_value=[])
    monkeypatch.setattr(TagManagementService, "get_agent_assignments_batch", service)
    with TestClient(app) as client:
        response = client.post("/tag-libraries/assignments/agent/batch_read", json={"agent_ids": ["2", "1", "2"]})
        assert response.status_code == 200
        assert response.json() == []
        caller, ids = service.call_args.args
        assert (caller.authenticated_tenant_id, caller.role, ids) == ("tenant-a", "USER", [2, 1])
        for body in [{"agent_ids": []}, {"agent_ids": [0]}, {"agent_ids": [1], "tenant_id": "other"}]:
            assert client.post("/tag-libraries/assignments/agent/batch_read", json=body).status_code == 422
        service.assert_called_once()


def test_agent_batch_preserves_read_permissions_and_never_resolves_individually(monkeypatch):
    agents = MagicMock(return_value=[
        {"agent_id": 1, "tenant_id": "tenant-a", "created_by": "other", "ingroup_permission": "READ_ONLY"},
        {"agent_id": 2, "tenant_id": "tenant-a", "created_by": "reader", "ingroup_permission": "NONE"},
        {"agent_id": 3, "tenant_id": "tenant-a", "created_by": "other", "ingroup_permission": "NONE"},
    ])
    assignments = MagicMock(return_value={"2": [{"value_id": 9}], "1": []})
    monkeypatch.setattr("services.tag_management_service.query_agent_info_by_ids", agents)
    monkeypatch.setattr(TagManagementDB, "list_resource_assignments_batch", assignments)
    monkeypatch.setattr(TagManagementService, "_resolve_assignment_resource", MagicMock(side_effect=AssertionError("N+1")))
    caller = AuthenticatedCaller("reader", "tenant-a", role="USER")
    result = TagManagementService.get_agent_assignments_batch(caller, [2, 3, 99, 1, 2])
    agents.assert_called_once_with("tenant-a", [2, 3, 99, 1])
    assignments.assert_called_once_with("tenant-a", "agent", ["2", "1"], "default_resource")
    assert [x["resource_id"] for x in result] == ["2", "1"]
    assert [x["assignment_count"] for x in result] == [1, 0]
    assert result[1]["assignments"] == []
    assert TagManagementService.get_agent_assignments_batch(caller, []) == []
    agents.assert_called_once()


def test_agent_batch_query_is_tenant_draft_active_and_one_in_query(monkeypatch):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.all.return_value = []
    context = MagicMock()
    context.__enter__.return_value = session
    monkeypatch.setattr("database.agent_db.get_db_session", lambda: context)
    assert query_agent_info_by_ids("tenant-a", [1, 2]) == []
    session.query.assert_called_once()
    query.all.assert_called_once()
    criteria = {criterion.left.key: criterion.right.value for criterion in query.filter.call_args.args}
    assert criteria == {"tenant_id": "tenant-a", "version_no": 0, "delete_flag": "Y", "agent_id": [1, 2]}
