# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Isolated Skill mount projection, configuration and HTTP routing regressions."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from management.api.skill import skill as skill_api
from management.db.skill import repository as skill_db
from management.services.skill import service as skill_service


def metadata(skill_id=1, creator="viewer"):
    return dict(
        skill_id=skill_id, name=f"Skill {skill_id}", tenant_id="tenant-a",
        description="Mount description", tags=["test"], source="local",
        config_schemas=[{"name": "region", "type": "string", "required": True}],
        config_values={"region": "west"}, group_ids=[], ingroup_permission="PRIVATE",
        created_by=creator, updated_by=creator, create_time=None, update_time=None,
    )


@pytest.fixture
def repository_session(mocker):
    query = MagicMock()
    query.options.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    session = MagicMock()
    session.query.return_value = query
    context = MagicMock()
    context.__enter__.return_value = session
    mocker.patch.object(skill_db, "get_db_session", return_value=context)
    return session, query


def database_row():
    row = metadata()
    for source, target in [("name", "skill_name"), ("description", "skill_description"), ("tags", "skill_tags")]:
        row[target] = row.pop(source)
    row["group_ids"] = ""

    class WithoutContent(SimpleNamespace):
        @property
        def skill_content(self):
            raise AssertionError("Mount listing must not read deferred content")

    return WithoutContent(**row)


def test_mount_query_excludes_body_and_tool_relations(mocker, repository_session):
    _, query = repository_session
    query.all.return_value = [database_row()]
    relations = mocker.patch.object(skill_db, "_get_tool_ids", side_effect=AssertionError("No tool lookup"))

    result = skill_db.list_skill_mount_summaries("tenant-a")

    assert result == [metadata()]
    relations.assert_not_called()
    option = query.options.call_args.args[0]
    sql = str(select(skill_db.SkillInfo).options(option))
    assert "skill_content" not in sql
    filters = query.filter.call_args.args
    params = [expression.compile().params for expression in filters]
    assert any("tenant-a" in values.values() for values in params)
    assert any("Y" in values.values() for values in params)
    assert len(query.order_by.call_args.args) == 2


def test_mount_query_empty_catalog_never_queries_relations(mocker, repository_session):
    _, query = repository_session
    query.all.return_value = []
    relations = mocker.patch.object(skill_db, "_get_tool_ids")
    assert skill_db.list_skill_mount_summaries("tenant-a") == []
    relations.assert_not_called()


def test_mount_service_retains_visibility_and_configuration(mocker):
    summaries = mocker.patch.object(skill_service.skill_db, "list_skill_mount_summaries", create=True,
                                   return_value=[metadata(), metadata(2, "other")])
    full = mocker.patch.object(skill_service.skill_db, "list_skills")
    mocker.patch.object(skill_service, "_get_user_role", return_value="USER")
    mocker.patch.object(skill_service, "query_group_ids_by_user", return_value=[])
    service = skill_service.SkillService(tenant_id="tenant-a", skill_manager=MagicMock())
    mocker.patch.object(service, "_enrich_configs_from_yaml", side_effect=lambda skill: skill)

    rows = service.list_visible_skills(tenant_id="tenant-a", user_id="viewer", for_mount=True)

    assert [row["skill_id"] for row in rows] == [1]
    assert rows[0]["config_values"] == {"region": "west"}
    assert rows[0]["config_schemas"][0]["required"] is True
    assert rows[0]["permission"] == "EDIT"
    assert "content" not in rows[0] and "tool_ids" not in rows[0]
    summaries.assert_called_once_with("tenant-a")
    full.assert_not_called()


def test_mount_service_maps_database_failure(mocker):
    mocker.patch.object(skill_service.skill_db, "list_skill_mount_summaries", create=True,
                      side_effect=RuntimeError("unavailable"))
    service = skill_service.SkillService(tenant_id="tenant-a", skill_manager=MagicMock())
    with pytest.raises(skill_service.SkillException, match="Failed to list skills"):
        service.list_skills(for_mount=True)


@pytest.mark.parametrize("view", [None, "full", "mount"])
def test_skill_api_routes_opt_in_without_changing_full_default(mocker, view):
    mocker.patch.object(skill_api, "get_current_user_id", return_value=("viewer", "tenant-a"))
    mocker.patch.object(skill_api, "resource_read_tenant", return_value=None)
    service = mocker.patch.object(skill_api, "SkillService").return_value
    service.list_visible_skills.return_value = [metadata()]
    app = FastAPI()
    app.include_router(skill_api.router)
    response = TestClient(app).get("/skills", params={} if view is None else {"view": view})
    assert response.status_code == 200
    expected = dict(tenant_id="tenant-a", user_id="viewer")
    if view == "mount":
        expected["for_mount"] = True
    service.list_visible_skills.assert_called_once_with(**expected)


def test_skill_api_rejects_unknown_view(mocker):
    auth = mocker.patch.object(skill_api, "get_current_user_id")
    app = FastAPI()
    app.include_router(skill_api.router)
    response = TestClient(app).get("/skills", params={"view": "invalid"})
    assert response.status_code == 422
    auth.assert_not_called()
