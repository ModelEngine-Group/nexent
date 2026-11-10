# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral persistence and authorized execution reads for MCP tools."""

from itertools import groupby
from typing import Literal

from sqlalchemy import JSON, Boolean, Column, Integer, Sequence, String, Text, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from infrastructure.rdb.base import SCHEMA, TableBase
from infrastructure.rdb.skill_execution_records import SkillInfo, SkillInstance, SkillToolRelation, bound_skill_predicates
from infrastructure.skill_execution import merge_skill_tool_parameters

_MCP_NAME_DOC = "MCP name"


class McpRecord(TableBase):
    """
    MCP (Model Context Protocol) records table
    """
    __tablename__ = "mcp_record_t"
    __table_args__ = {"schema": SCHEMA}

    mcp_id = Column(Integer, Sequence("mcp_record_t_mcp_id_seq", schema=SCHEMA),
                    primary_key=True, nullable=False, doc="MCP record ID, unique primary key")
    tenant_id = Column(String(100), doc="Tenant ID")
    user_id = Column(String(100), doc="User ID")
    mcp_name = Column(String(100), doc=_MCP_NAME_DOC)
    mcp_server = Column(String(500), doc="MCP server address")
    status = Column(
        Boolean,
        default=None,
        doc="MCP server connection status, True=connected, False=disconnected, None=unknown",
    )
    container_id = Column(
        String(200),
        doc="Docker container ID for MCP service, None for non-containerized MCP",
    )
    container_port = Column(
        Integer,
        doc="Host port bound for containerized MCP service",
    )
    authorization_token = Column(
        String(500),
        doc="Authorization token for MCP server authentication (e.g., Bearer token)",
        default=None,
    )
    custom_headers = Column(
        JSON,
        doc="Custom HTTP headers as JSON object for MCP server requests",
        default=None,
    )
    source = Column(
        String(30), doc="Source type: local/mcp_registry/community")
    market_id = Column(Integer, doc="Published market record ID (FK to mcp_market_record_t)")
    registry_json = Column(JSONB, doc="Full MCP registry server.json snapshot")
    config_json = Column(JSON, doc="MCP config data")
    enabled = Column(Boolean, default=True, doc="Enabled")
    tags = Column(ARRAY(Text), doc="Tags")
    description = Column(Text, doc="Description")
    group_ids = Column(String, doc="Comma-separated group IDs that can access this MCP")
    ingroup_permission = Column(String(30), default="READ_ONLY",
                                 doc="In-group permission: EDIT, READ_ONLY, PRIVATE")
    shared_fields = Column(JSON, default=None,
                           doc="JSON object of field-level sharing flags (e.g. {\"serverUrl\": true, \"authorizationToken\": false})")


class ToolInfo(TableBase):
    """
    Information table for prompt tools
    """
    __tablename__ = "ag_tool_info_t"
    __table_args__ = {"schema": SCHEMA}

    tool_id = Column(Integer, primary_key=True, nullable=False, doc="ID")
    name = Column(String(100), doc="Unique key name")
    origin_name = Column(String(100), doc="Original name")
    class_name = Column(
        String(100), doc="Tool class name, used when the tool is instantiated")
    description = Column(String(2048), doc="Prompt tool description")
    source = Column(String(100), doc="Source")
    author = Column(String(100), doc="Tool author")
    usage = Column(String(100), doc="Usage")
    params = Column(JSON, doc="Tool parameter information (json)")
    inputs = Column(String(2048), doc="Prompt tool inputs description")
    output_type = Column(String(100), doc="Prompt tool output description")
    category = Column(String(100), doc="Tool category description")
    labels = Column(JSONB, default=[], doc="JSON array of label strings for filtering/grouping tools")
    is_user_selectable = Column(
        Boolean, default=True, nullable=False, doc="Whether users can actively select the tool in agent configuration")
    is_available = Column(
        Boolean, doc="Whether the tool can be used under the current main service")


class ToolInstance(TableBase):
    """
    Information table for tenant tool configuration.
    """
    __tablename__ = "ag_tool_instance_t"
    __table_args__ = {"schema": SCHEMA}

    tool_instance_id = Column(
        Integer,
        Sequence("ag_tool_instance_t_tool_instance_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="ID"
    )
    tool_id = Column(Integer, doc="Tenant tool ID")
    agent_id = Column(Integer, doc="Agent ID")
    params = Column(JSON, doc="Parameter configuration")
    user_id = Column(String(100), doc="User ID")
    tenant_id = Column(String(100), doc="Tenant ID")
    enabled = Column(Boolean, doc="Enabled")
    version_no = Column(Integer, default=0, primary_key=True, nullable=False,
                        doc="Version number. 0 = draft/editing state, >=1 = published snapshot")


def read_bound_mcp_tools(agent_id: int, version_no: int, tenant_id: str, names: list[str]) -> list[dict]:
    from infrastructure.rdb.client import get_db_session

    tool, instance = ToolInfo, ToolInstance
    with get_db_session() as session:
        rows = session.execute(select(
            instance.tool_instance_id, instance.params.label("instance_params"), tool.name, tool.class_name,
            tool.usage, tool.origin_name, tool.params, tool.description, tool.inputs, tool.output_type,
        ).join(instance, instance.tool_id == tool.tool_id).where(
            instance.agent_id == agent_id, instance.version_no == version_no, instance.tenant_id == tenant_id,
            instance.enabled.is_(True), instance.delete_flag != "Y",
            tool.source == "mcp", tool.author == tenant_id, tool.name.in_(names),
            tool.delete_flag != "Y", tool.is_available.is_not(False),
        )).mappings()
        return [dict(row) for row in rows]


def read_skill_derived_mcp_tools(agent_id: int, version_no: int, tenant_id: str, names: list[str]) -> list[dict]:
    """Resolve tenant-owned MCP tools contributed by active skills unless explicitly bound."""
    return read_skill_derived_tools(agent_id, version_no, tenant_id, names, source="mcp")


def read_skill_derived_tools(
    agent_id: int, version_no: int, tenant_id: str, names: list[str], *, source: Literal["mcp", "local"],
) -> list[dict]:
    """Read active skill contributions for tools of one catalog source."""
    from infrastructure.rdb.client import get_db_session

    tool, instance = ToolInfo, ToolInstance
    explicit = select(instance.tool_instance_id).where(
        instance.tool_id == tool.tool_id, instance.agent_id == agent_id, instance.version_no == version_no,
        instance.tenant_id == tenant_id, instance.enabled.is_(True), instance.delete_flag != "Y",
    ).exists()
    statement = (
        select(
            tool.tool_id, tool.name, tool.class_name, tool.usage, tool.origin_name, tool.params,
            tool.description, tool.inputs, tool.output_type, SkillInstance.skill_instance_id,
            SkillInfo.skill_name, SkillInfo.config_values.label("defaults"), SkillInstance.config_values.label("overrides"),
        )
        .select_from(tool)
        .join(SkillToolRelation, SkillToolRelation.tool_id == tool.tool_id)
        .join(SkillInfo, SkillInfo.skill_id == SkillToolRelation.skill_id)
        .join(SkillInstance, SkillInstance.skill_id == SkillInfo.skill_id)
        .where(
            *bound_skill_predicates(agent_id, version_no, tenant_id),
            tool.source == source, tool.name.in_(names),
            tool.delete_flag != "Y", tool.is_available.is_not(False), ~explicit,
            *((tool.author == tenant_id,) if source == "mcp" else ()),
        )
        .order_by(tool.tool_id, SkillInstance.skill_instance_id)
    )
    with get_db_session() as session:
        rows = session.execute(statement).mappings().all()

    tools = []
    for tool_id, group in groupby(rows, key=lambda row: row["tool_id"]):
        sources = {row["skill_instance_id"]: row for row in group}
        values = merge_skill_tool_parameters(tool_id, [
            (row["skill_name"], {**(row["defaults"] or {}), **(row["overrides"] or {})})
            for row in sources.values()
        ])
        row = next(iter(sources.values()))
        params = [
            {**param, "default": values[param["name"]]} if param["name"] in values else param
            for param in (row["params"] or [])
        ]
        tools.append({
            **{key: row[key] for key in ("tool_id", "name", "class_name", "usage", "origin_name",
                                         "description", "inputs", "output_type")},
            "params": params, "instance_params": {}, "skill_instance_ids": sorted(sources),
        })
    return tools


def read_mcp_execution_servers(tenant_id: str) -> list[dict]:
    from infrastructure.rdb.client import get_db_session

    server = McpRecord
    with get_db_session() as session:
        rows = session.execute(select(
            server.mcp_id, server.mcp_name, server.mcp_server, server.authorization_token,
            server.custom_headers, server.enabled,
        ).where(
            server.tenant_id == tenant_id, server.delete_flag != "Y", server.status.is_(True),
        )).mappings()
        return [dict(row) for row in rows]
