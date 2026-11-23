# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tool names omitted from the effective catalog of one published business Agent."""

from sqlalchemy import Column, Integer, String, Table, insert, select

from infrastructure.rdb.base import SCHEMA, TableBase


excluded_tool = Table(
    "evolution_release_excluded_tool_t",
    TableBase.metadata,
    Column("tenant_id", String(100), primary_key=True),
    Column("agent_id", Integer, primary_key=True),
    Column("version_no", Integer, primary_key=True),
    Column("tool_name", String, primary_key=True),
    schema=SCHEMA,
)


def excluded_for_version(session, tenant, agent, version):
    c = excluded_tool.c
    return list(
        session.scalars(
            select(c.tool_name)
            .where(c.tenant_id == tenant, c.agent_id == agent, c.version_no == version)
            .order_by(c.tool_name)
        )
    )


def publish_tool_selection(session, tenant, agent, base, version, removed):
    names = set(excluded_for_version(session, tenant, agent, base)).union(removed)
    if names:
        session.execute(
            insert(excluded_tool),
            [
                dict(tenant_id=tenant, agent_id=agent, version_no=version, tool_name=name)
                for name in sorted(names)
            ],
        )
