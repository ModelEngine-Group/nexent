# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Sequence,
    String,
    Text,
)


from sqlalchemy.dialects.postgresql import JSONB


from infrastructure.rdb.mcp_execution_records import ToolInfo as ToolInfo, ToolInstance as ToolInstance
from management.db.base import SCHEMA, TableBase


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
