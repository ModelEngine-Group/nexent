# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read enabled local SDK tool instances in the requested Agent version."""

from sqlalchemy import select

from infrastructure.rdb.mcp_execution_records import ToolInfo, ToolInstance, read_skill_derived_tools


def read_bound_local_tools(agent_id: int, version_no: int, tenant_id: str, names: list[str]) -> list[dict]:
    from infrastructure.rdb.client import get_db_session

    tool, instance = ToolInfo, ToolInstance
    with get_db_session() as session:
        rows = session.execute(select(
            instance.tool_instance_id, instance.params.label("instance_params"), tool.tool_id, tool.name,
            tool.class_name, tool.source, tool.usage, tool.params, tool.description, tool.inputs, tool.output_type,
        ).join(instance, instance.tool_id == tool.tool_id).where(
            instance.agent_id == agent_id, instance.version_no == version_no, instance.tenant_id == tenant_id,
            instance.enabled.is_(True), instance.delete_flag != "Y",
            tool.source == "local", tool.name.in_(names), tool.delete_flag != "Y", tool.is_available.is_not(False),
        )).mappings()
        return [dict(row) for row in rows]


def read_skill_derived_local_tools(agent_id: int, version_no: int, tenant_id: str, names: list[str]) -> list[dict]:
    return [
        {**row, "source": "local"}
        for row in read_skill_derived_tools(agent_id, version_no, tenant_id, names, source="local")
    ]
