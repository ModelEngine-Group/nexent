# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Integer,
    Sequence,
    String,
    Text,
)


from sqlalchemy.dialects.postgresql import JSONB


from management.db.base import SCHEMA, TableBase


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
    outer_api_service_id = Column(
        BigInteger,
        nullable=True,
        index=True,
        doc="Source API-to-MCP service ID; NULL for non-OpenAPI tools",
    )
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


class OuterApiService(TableBase):
    """
    OpenAPI service table - stores MCP service information converted from OpenAPI specs.
    Each record represents one MCP service with its OpenAPI specification.
    """
    __tablename__ = "ag_outer_api_services"
    __table_args__ = {"schema": SCHEMA}

    id = Column(BigInteger, Sequence("ag_outer_api_services_id_seq", schema=SCHEMA),
                primary_key=True, nullable=False, doc="Service ID, unique primary key")
    mcp_service_name = Column(String(100), nullable=False,
                              doc="MCP service name (unique identifier per tenant)")
    description = Column(Text, doc="Service description from OpenAPI info")
    openapi_json = Column(JSONB, doc="Complete OpenAPI JSON specification")
    server_url = Column(String(500), doc="Base URL of the REST API server")
    headers_template = Column(JSONB, doc="Default headers template as JSON")
    tenant_id = Column(String(100), nullable=False,
                       doc="Tenant ID for multi-tenancy")
    is_available = Column(Boolean, default=True,
                          doc="Whether the service is available")


# Retain the public name used by older outer API query callers.
OuterApiTool = OuterApiService
