# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read enabled local SDK tool instances in the requested Agent version."""

from sqlalchemy import select

from infrastructure.rdb.mcp_execution_records import ToolInfo, ToolInstance, read_skill_derived_tools


def read_bound_local_tools(agent_id: int, version_no: int, tenant_id: str, names: list[str]) -> list[dict]:
    return read_bound_catalog_tools(agent_id, version_no, tenant_id, names, source="local")


def read_bound_catalog_tools(agent_id: int, version_no: int, tenant_id: str, names: list[str], *, source: str) -> list[dict]:
    from infrastructure.rdb.client import get_db_session

    tool, instance = ToolInfo, ToolInstance
    with get_db_session() as session:
        rows = session.execute(select(
            instance.tool_instance_id, instance.params.label("instance_params"), tool.tool_id, tool.name,
            tool.class_name, tool.source, tool.usage, tool.params, tool.description, tool.inputs, tool.output_type,
        ).join(instance, instance.tool_id == tool.tool_id).where(
            instance.agent_id == agent_id, instance.version_no == version_no, instance.tenant_id == tenant_id,
            instance.enabled.is_(True), instance.delete_flag != "Y",
            tool.source == source, tool.name.in_(names), tool.delete_flag != "Y", tool.is_available.is_not(False),
        )).mappings()
        return [dict(row) for row in rows]


def read_shared_aidp_catalog_tool(tool_id: int, tenant_id: str) -> dict | None:
    """Read the tenant-owned catalog tool used for a request-local Workbench mount."""
    from infrastructure.rdb.client import get_db_session

    tool = ToolInfo
    with get_db_session() as session:
        row = session.execute(select(
            tool.tool_id, tool.name, tool.class_name, tool.source, tool.usage, tool.params,
            tool.description, tool.inputs, tool.output_type,
        ).where(
            tool.tool_id == tool_id, tool.author == tenant_id, tool.name == "aidp_search",
            tool.class_name == "AidpSearchTool", tool.source == "local",
            tool.delete_flag != "Y", tool.is_available.is_(True),
        )).mappings().one_or_none()
    return {**row, "instance_params": {}} if row is not None else None


def read_skill_derived_local_tools(agent_id: int, version_no: int, tenant_id: str, names: list[str]) -> list[dict]:
    return [
        {**row, "source": "local"}
        for row in read_skill_derived_tools(agent_id, version_no, tenant_id, names, source="local")
    ]
