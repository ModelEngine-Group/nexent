# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, create_engine

from infrastructure.rdb.mcp_execution_records import ToolInfo
from management.db.configuration.resource_denylist import tool_catalog


@pytest.mark.parametrize("tenant", [None, "tenant-a", "tenant-b"])
def test_editor_catalog_only_contains_intrinsically_selectable_tools(tenant):
    engine = create_engine("sqlite://", execution_options={
        "schema_translate_map": {ToolInfo.__table__.schema: None},
    })
    table = Table(ToolInfo.__tablename__, MetaData(),
                  Column("tool_id", Integer, primary_key=True),
                  *(Column(name, String) for name in (
                      "name", "origin_name", "source", "usage", "description", "author", "delete_flag")),
                  Column("is_available", Boolean), Column("is_user_selectable", Boolean))
    table.create(engine)
    variants = [
        ("selectable", None, True, True, "N"),
        ("ind_aidp_search", None, True, True, "N"),
        ("aidp_search", None, True, True, "N"),
        ("knowledge_base_search", None, True, True, "N"),
        ("knowledge_alias", "aidp_search", True, True, "N"),
        ("download_from_s3", None, True, True, "N"),
        ("upload_to_s3", None, True, True, "N"),
        ("store_memory", None, True, True, "N"),
        ("search_memory", None, True, True, "N"),
        ("parallel_executor", None, True, True, "N"),
        ("not_selectable", None, False, True, "N"),
        ("unavailable", None, True, False, "N"),
        ("deleted", None, True, True, "Y"),
    ]
    try:
        with engine.begin() as connection:
            connection.execute(table.insert(), [
                dict(name=name, origin_name=origin, is_user_selectable=selectable,
                     is_available=available, delete_flag=deleted, author=owner,
                     source="local", usage=None, description="Catalog eligibility")
                for owner in ("tenant-a", "tenant-b")
                for name, origin, selectable, available, deleted in variants
            ])
            rows = tool_catalog(connection, tenant)
            assert {row["name"] for row in rows} == {"selectable", "ind_aidp_search"}
            assert len(rows) == 2
            if tenant is not None:
                assert all((row["tool_id"] <= len(variants)) == (tenant == "tenant-a") for row in rows)
    finally:
        engine.dispose()


def test_global_catalog_deduplicates_name_source_and_service_but_tenant_keeps_ids():
    engine = create_engine("sqlite://", execution_options={
        "schema_translate_map": {ToolInfo.__table__.schema: None},
    })
    table = Table(ToolInfo.__tablename__, MetaData(),
                  Column("tool_id", Integer, primary_key=True),
                  *(Column(name, String) for name in (
                      "name", "origin_name", "source", "usage", "description", "author", "delete_flag")),
                  Column("is_available", Boolean), Column("is_user_selectable", Boolean))
    table.create(engine)
    variants = [
        ("search", "mcp", "service-a", "Zulu", "tenant-a"),
        ("search", "mcp", "service-a", "Alpha", "tenant-b"),
        ("search", "mcp", "service-a", "", "tenant-b"),
        ("search", "mcp", "service-b", "Other service", "tenant-a"),
        ("search", "local", "System", "Local", "tenant-a"),
        ("search", "local", "Other category", None, "tenant-b"),
        ("lookup", "mcp", "service-a", None, "tenant-a"),
    ]
    try:
        with engine.begin() as connection:
            connection.execute(table.insert(), [
                dict(name=name, source=source, usage=usage, description=description,
                     author=tenant, origin_name=None, delete_flag="N", is_available=True,
                     is_user_selectable=True)
                for name, source, usage, description, tenant in variants
            ])
            rows = tool_catalog(connection)
            assert len(rows) == 4
            assert {(row["name"], row["source"], row["usage"]) for row in rows} == {
                ("search", "mcp", "service-a"), ("search", "mcp", "service-b"),
                ("search", "local", None), ("lookup", "mcp", "service-a"),
            }
            assert next(row for row in rows if row["name"] == "search" and row["usage"] == "service-a")["description"] == "Alpha"
            assert next(row for row in rows if row["name"] == "lookup")["description"] is None
            tenant_rows = tool_catalog(connection, "tenant-b")
            assert {row["tool_id"] for row in tenant_rows} == {2, 3, 6}
            assert len(tenant_rows) == 3
    finally:
        engine.dispose()
