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


from sqlalchemy.dialects.postgresql import ARRAY, JSONB


from management.db.base import (
    SCHEMA,
    TableBase,
    _MCP_NAME_DOC,
    _PUBLISHER_TENANT_ID_DOC,
    _PUBLISHER_USER_ID_DOC,
    _TENANT_ID_DOC,
)


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


class McpCommunityRecord(TableBase):
    """Community MCP market records table."""

    __tablename__ = "mcp_community_record_t"
    __table_args__ = {"schema": SCHEMA}

    community_id = Column(
        Integer,
        Sequence("mcp_community_record_t_community_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="Community record ID, unique primary key",
    )
    tenant_id = Column(String(100), doc=_PUBLISHER_TENANT_ID_DOC)
    user_id = Column(String(100), doc=_PUBLISHER_USER_ID_DOC)
    mcp_name = Column(String(100), doc=_MCP_NAME_DOC)
    mcp_server = Column(String(500), doc="MCP server URL")
    source = Column(String(30), doc="Source type, fixed to community")
    registry_json = Column(JSONB, doc="Full MCP metadata JSON")
    transport_type = Column(
        String(30), doc="Transport type: http/sse/container")
    config_json = Column(JSON, doc="Public-shareable MCP configuration JSON")
    review_status = Column(
        String(30), default="pending", doc="Review status: pending/approved/rejected/offline")
    review_type = Column(
        String(30), default="initial_listing", doc="Review submission type: initial_listing/update")
    tags = Column(ARRAY(Text), doc="Tags")
    description = Column(Text, doc="Description")


class McpMarketRecord(TableBase):
    """MCP market (community) record — single table covering all listing states."""

    __tablename__ = "mcp_market_record_t"
    __table_args__ = {"schema": SCHEMA}

    market_id = Column(
        BigInteger,
        Sequence("mcp_market_record_t_market_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="Market record ID, unique primary key",
    )
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    user_id = Column(String(100), nullable=False, doc="Publisher user ID")
    mcp_name = Column(String(100), doc=_MCP_NAME_DOC)
    mcp_server = Column(String(500), doc="MCP server URL")
    source = Column(String(30), doc="Source type, fixed to community")
    registry_json = Column(JSONB, doc="Full MCP metadata JSON")
    transport_type = Column(String(30), doc="Transport type: http/sse/container")
    config_json = Column(JSON, doc="Public-shareable MCP configuration JSON")
    tags = Column(ARRAY(Text), doc="Tags")
    description = Column(Text, doc="Description")
    content = Column(Text, doc="Listing note on submit or review opinion on approve/reject")
    download_count = Column(Integer, default=0, doc="Cumulative download/install count")
    review_status = Column(String(30), default="not_shared",
                           doc="Listing status: not_shared / pending_review / rejected / shared")
    submitted_by = Column(String(100), doc="Submitter email when listing enters pending_review")
    source_mcp_id = Column(Integer, doc="Local MCP record ID that created this market record")
    group_ids = Column(String, doc="Comma-separated group IDs that can access this MCP")
    ingroup_permission = Column(String(30), default="READ_ONLY",
                                 doc="In-group permission: EDIT, READ_ONLY, PRIVATE")
    shared_fields = Column(JSON, default=None,
                           doc="Snapshot of shared_fields at submission time")
