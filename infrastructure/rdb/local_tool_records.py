# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read enabled local SDK tool instances in the requested Agent version."""

from sqlalchemy import select, text

from contracts.constants.constants import ASSET_OWNER_TENANT_ID

from infrastructure.rdb.mcp_execution_records import ToolInfo, ToolInstance, read_skill_derived_tools


def read_bound_local_tools(agent_id: int, version_no: int, tenant_id: str, names: list[str]) -> list[dict]:
    return read_bound_catalog_tools(agent_id, version_no, tenant_id, names, source="local")


def read_bound_catalog_tools(agent_id: int, version_no: int, tenant_id: str, names: list[str], *, source: str) -> list[dict]:
    from infrastructure.rdb.client import get_db_session

    statement = _bound_catalog_tools(agent_id, version_no, tenant_id, names, source)
    with get_db_session() as session:
        return [dict(row) for row in session.execute(statement).mappings()]


def _bound_catalog_tools(agent_id: int, version_no: int, tenant_id: str, names: list[str], source: str):
    tool, instance = ToolInfo, ToolInstance
    return select(
        instance.tool_instance_id, instance.params.label("instance_params"), tool.tool_id, tool.name,
        tool.class_name, tool.source, tool.usage, tool.params, tool.description, tool.inputs, tool.output_type,
    ).join(instance, instance.tool_id == tool.tool_id).where(
        instance.agent_id == agent_id, instance.version_no == version_no, instance.tenant_id == tenant_id,
        instance.enabled.is_(True), instance.delete_flag != "Y",
        tool.source == source, tool.name.in_(names), tool.delete_flag != "Y", tool.is_available.is_not(False),
    )


def read_workbench_default_aidp_tools(agent_id: int, version_no: int) -> list[dict]:
    """Read the platform AIDP instance of the exact published Workbench root."""
    from infrastructure.rdb.client import get_db_session

    published_root = text("""
        EXISTS (
            SELECT 1 FROM nexent.ag_tenant_agent_t
            WHERE agent_id = :workbench_agent_id AND version_no = :workbench_version_no
              AND version_no > 0 AND tenant_id = :asset_owner
              AND system_key = 'workbench_main' AND agent_origin = 'SYSTEM'
              AND delete_flag = 'N' AND enabled IS NOT FALSE
        )
    """).bindparams(
        workbench_agent_id=agent_id, workbench_version_no=version_no, asset_owner=ASSET_OWNER_TENANT_ID,
    )
    statement = _bound_catalog_tools(agent_id, version_no, ASSET_OWNER_TENANT_ID, ["aidp_search"], "local").where(
        ToolInfo.author == ASSET_OWNER_TENANT_ID, ToolInfo.class_name == "AidpSearchTool", published_root,
    )
    with get_db_session() as session:
        return [dict(row) for row in session.execute(statement).mappings()]


def read_workbench_scoped_aidp_tool(tool_id: int, agent_id: int, version_no: int) -> dict | None:
    """Use the enabled platform binding to authorize a request-scoped catalog reference."""
    matches = [
        row for row in read_workbench_default_aidp_tools(agent_id, version_no) if row["tool_id"] == tool_id
    ]
    return {**matches[0], "instance_params": {}} if len(matches) == 1 else None


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
