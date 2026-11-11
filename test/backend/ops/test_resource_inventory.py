# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the inventory query against isolated relational records."""

from contextlib import nullcontext

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from management.db.models import AgentInfo, KnowledgeRecord, McpRecord, ModelRecord
from ops.services import access
from permissions.models import CurrentUser


@pytest.fixture
def inventory(mocker):
    records = (
        (AgentInfo, ("agent_id", "name", "version_no", "prompt"), [
            (1, "Agent A", 0, "synthetic prompt", "a", "N"),
            (1, "Published snapshot", 1, "snapshot prompt", "a", "N"),
            (2, "Agent B", 0, "synthetic prompt", "b", "N"),
        ]),
        (KnowledgeRecord, ("knowledge_id", "knowledge_name", "knowledge_describe"), [
            (3, "Knowledge A", "synthetic content", "a", "N"),
        ]),
        (McpRecord, ("mcp_id", "mcp_name", "authorization_token"), [
            (4, "MCP A", "synthetic token", "a", "N"),
            (5, "Deleted MCP", "synthetic token", "a", "Y"),
        ]),
        (ModelRecord, ("model_id", "model_name", "api_key"), [
            (6, "Model A", "synthetic key", "a", "N"),
        ]),
    )
    metadata = MetaData()
    engine = create_engine("sqlite://")
    schema_map = {model.__table__.schema: None for model, _, _ in records}
    try:
        with engine.begin() as connection:
            connection = connection.execution_options(schema_translate_map=schema_map)
            for model, fields, rows in records:
                columns = (*fields, "tenant_id", "delete_flag")
                source = model.__table__
                table = Table(
                    source.name, metadata,
                    *(Column(field, source.c[field].type) for field in columns),
                    schema=source.schema,
                )
                table.create(connection)
                connection.execute(table.insert(), [dict(zip(columns, row, strict=True)) for row in rows])
        with Session(engine.execution_options(schema_translate_map=schema_map)) as session:
            db = mocker.patch.object(access, "get_db_session", side_effect=lambda: nullcontext(session))
            mocker.patch(
                "permissions.operations.has_permission",
                side_effect=lambda roles, action: action == "resource.inventory:read" and bool(set(roles) & {"OPS", "SU"}),
            )
            yield db
    finally:
        engine.dispose()


def test_tenant_inventory_lists_only_active_metadata_from_all_resource_kinds(inventory):
    user = CurrentUser("operator", "a", "DEV", roles=("DEV", "OPS"))

    assert access.resource_inventory(user) == {
        "total": 4, "page": 1, "page_size": 20,
        "items": [
            {"kind": "agent", "id": 1, "name": "Agent A", "tenant_id": "a"},
            {"kind": "knowledge", "id": 3, "name": "Knowledge A", "tenant_id": "a"},
            {"kind": "mcp", "id": 4, "name": "MCP A", "tenant_id": "a"},
            {"kind": "model", "id": 6, "name": "Model A", "tenant_id": "a"},
        ],
    }


def test_platform_inventory_paginates_after_tenant_filter(inventory):
    user = CurrentUser("platform-admin", "a", "SU")

    assert access.resource_inventory(user, page=2, page_size=1) == {
        "total": 5, "page": 2, "page_size": 1,
        "items": [{"kind": "agent", "id": 2, "name": "Agent B", "tenant_id": "b"}],
    }
    assert access.resource_inventory(user, "b", page=2, page_size=1) == {
        "total": 1, "page": 2, "page_size": 1, "items": [],
    }


def test_tenant_inventory_rejects_foreign_scope_before_opening_database(inventory):
    with pytest.raises(HTTPException) as error:
        access.resource_inventory(CurrentUser("operator", "a", "OPS"), "b")

    assert error.value.status_code == 403
    inventory.assert_not_called()
