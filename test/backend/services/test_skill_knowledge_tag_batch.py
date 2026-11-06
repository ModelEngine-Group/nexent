# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from management.api.tag import tag_management as tag_management_app
from management.db.skill.repository import get_skills_for_tag_read
from management.db.knowledge_base.repository import get_knowledge_records_for_tag_read
from management.db.tag.repository import TagManagementDB
from management.services.knowledge_base import permission
from management.services.tag.library import TagManagementService
from management.services.tag.resources import AuthenticatedCaller


@pytest.mark.parametrize("resource,field,valid,invalid", [
    ("skill", "skill_ids", ["1", "2", "1"], [[], [0], [2**63], list(range(1, 502))]),
    ("knowledge_base", "index_names", ["kb:a", "kb-b", "kb:a"], [[], [" "], ["a" * 1025], ["a"] * 501]),
])
def test_batch_http_validation_and_authenticated_scope(monkeypatch, resource, field, valid, invalid):
    app = FastAPI()
    app.include_router(tag_management_app.router)
    monkeypatch.setattr(tag_management_app, "get_current_user_context", lambda _: ("reader", "tenant-a", "DEV"))
    service = MagicMock(return_value=[])
    method = "get_skill_assignments_batch" if resource == "skill" else "get_knowledge_assignments_batch"
    monkeypatch.setattr(TagManagementService, method, service)
    with TestClient(app) as client:
        path = f"/tag-libraries/assignments/{resource}/batch_read"
        assert client.post(path, json={field: valid}).status_code == 200
        caller, ids = service.call_args.args
        assert caller.authenticated_tenant_id == "tenant-a"
        assert ids == ([1, 2] if resource == "skill" else ["kb:a", "kb-b"])
        for values in invalid:
            assert client.post(path, json={field: values}).status_code == 422
        assert client.post(path, json={field: valid, "tenant_id": "other"}).status_code == 422
        service.assert_called_once()


def test_skill_batch_preserves_group_restrictions_and_uses_one_record_read(monkeypatch):
    records = MagicMock(return_value=[
        {"skill_id": 1, "created_by": "reader", "group_ids": [9]},
        {"skill_id": 2, "created_by": "other", "group_ids": [9]},
        {"skill_id": 3, "created_by": "other", "group_ids": []},
    ])
    monkeypatch.setattr("management.services.tag.library.get_skills_for_tag_read", records)
    assignments = MagicMock(return_value={"3": [], "1": [{"value_id": 8}]})
    monkeypatch.setattr(TagManagementDB, "list_resource_assignments_batch", assignments)
    caller = AuthenticatedCaller("reader", "tenant-a", role="DEV")
    result = TagManagementService.get_skill_assignments_batch(caller, [3, 2, 1, 99, 3])
    records.assert_called_once_with("tenant-a", [3, 2, 1, 99])
    assignments.assert_called_once_with("tenant-a", "skill", ["3", "1"], "default_resource")
    assert [x["assignment_count"] for x in result] == [0, 1]


def test_knowledge_batch_uses_real_access_rules_with_one_context_read(monkeypatch):
    records = [
        {"index_name": "owned", "tenant_id": "tenant-a", "created_by": "reader"},
        {"index_name": "group", "tenant_id": "tenant-a", "created_by": "other", "group_ids": [9], "ingroup_permission": "READ_ONLY"},
        {"index_name": "denied", "tenant_id": "tenant-a", "created_by": "other", "group_ids": [8]},
    ]
    record_read = MagicMock(return_value=records)
    monkeypatch.setattr("management.services.tag.library.get_knowledge_records_for_tag_read", record_read)
    role = MagicMock(return_value={"tenant_id": "tenant-a", "user_role": "DEV"})
    groups = MagicMock(return_value=[9])
    monkeypatch.setattr(permission, "get_user_tenant_by_user_id", role)
    monkeypatch.setattr(permission, "query_group_ids_by_user", groups)
    monkeypatch.setattr(permission, "IS_SPEED_MODE", False)
    assignments = MagicMock(return_value={"owned": [], "group": []})
    monkeypatch.setattr(TagManagementDB, "list_resource_assignments_batch", assignments)
    result = TagManagementService.get_knowledge_assignments_batch(
        AuthenticatedCaller("reader", "tenant-a", role="DEV"), ["owned", "denied", "missing", "group"]
    )
    assert [x["resource_id"] for x in result] == ["owned", "group"]
    record_read.assert_called_once()
    role.assert_called_once_with("reader")
    groups.assert_called_once_with("reader")
    assignments.assert_called_once_with("tenant-a", "knowledge_base", ["owned", "group"], "default_resource")
    monkeypatch.setattr(permission, "get_knowledge_record", lambda _: records[0])
    assert permission.resolve_knowledge_base_permission("owned", "reader", "tenant-a") == "CREATOR"


@pytest.mark.parametrize("speed,user_id,tenant,user_tenant", [
    (True, "reader", None, None),
    (False, "tenant-a", "tenant-a", {"tenant_id": "tenant-a", "user_role": "USER"}),
    (False, "reader", "tenant-a", {"tenant_id": "tenant-a", "user_role": "ADMIN"}),
])
def test_knowledge_batch_preserves_speed_and_legacy_admin_roles(monkeypatch, speed, user_id, tenant, user_tenant):
    monkeypatch.setattr(permission, "get_user_tenant_by_user_id", lambda _: user_tenant)
    monkeypatch.setattr(permission, "IS_SPEED_MODE", speed)
    monkeypatch.setattr(permission, "query_group_ids_by_user", lambda _: [])
    result = permission.resolve_knowledge_base_permissions(
        [{"index_name": "kb", "tenant_id": "tenant-a", "created_by": "other"}], user_id, tenant
    )
    assert result["kb"] in {"EDIT", "READ_ONLY"}


def test_knowledge_without_user_membership_denies_without_group_lookup(monkeypatch):
    monkeypatch.setattr(permission, "get_user_tenant_by_user_id", lambda _: None)
    monkeypatch.setattr(permission, "IS_SPEED_MODE", False)
    group_read = MagicMock()
    monkeypatch.setattr(permission, "query_group_ids_by_user", group_read)
    assert permission.resolve_knowledge_base_permissions([{"index_name": "kb"}], "reader", "t") == {"kb": None}
    group_read.assert_not_called()


@pytest.mark.parametrize("loader,module,id_field,ids", [
    (get_skills_for_tag_read, "management.db.skill.repository", "skill_id", [1, 2]),
    (get_knowledge_records_for_tag_read, "management.db.knowledge_base.repository", "index_name", ["a", "b"]),
])
def test_visibility_queries_are_single_tenant_scoped_in_reads(monkeypatch, loader, module, id_field, ids):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.all.return_value = []
    context = MagicMock()
    context.__enter__.return_value = session
    monkeypatch.setattr(module + ".get_db_session", lambda: context)
    assert loader("tenant-a", ids) == []
    query.all.assert_called_once()
    session.query.assert_called_once()
    criteria = {c.left.key: c.right.value for c in query.filter.call_args.args}
    assert criteria == {"tenant_id": "tenant-a", "delete_flag": "Y", id_field: ids}
    assert loader("tenant-a", []) == []
    session.query.assert_called_once()
