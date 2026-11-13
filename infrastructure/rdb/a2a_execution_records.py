# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persistence for external A2A endpoints and enabled runtime bindings."""

from sqlalchemy import JSON, TIMESTAMP, BigInteger, Boolean, Column, Integer, String, Text, UniqueConstraint, select

from contracts.constants.constants import PROTOCOL_JSONRPC
from infrastructure.rdb.base import SCHEMA, TableBase

_PRIMARY_KEY_DOC = "Primary key, auto-increment"
_TENANT_ID_DOC = "Tenant ID for multi-tenancy isolation"


class A2AExternalAgent(TableBase):
    """
    External A2A agents discovered from URL or Nacos.
    Caches Agent Cards for A2A Client role.
    """
    __tablename__ = "ag_a2a_external_agent_t"
    __table_args__ = {"schema": SCHEMA}

    id = Column(BigInteger, primary_key=True,
                autoincrement=True, doc=_PRIMARY_KEY_DOC)

    # Agent metadata (cached from Agent Card)
    name = Column(String(255), nullable=False,
                  doc="Agent name from Agent Card")
    description = Column(Text, doc="Agent description from Agent Card")
    version = Column(
        String(50), doc="Agent version from Agent Card, e.g., 1.2.0")

    # Primary interface (extracted from supportedInterfaces for quick access)
    # In A2A 1.0, this should store the http-json-rpc URL
    agent_url = Column(String(512), nullable=False,
                       doc="Primary A2A endpoint URL (http-json-rpc by default)")

    # Protocol type for calling this agent: JSONRPC, HTTP+JSON, GRPC
    protocol_type = Column(String(20), default=PROTOCOL_JSONRPC,
                           doc="Protocol type for calling this agent")

    # Capabilities
    streaming = Column(Boolean, default=False,
                       doc="Whether this agent supports SSE streaming")

    # All supported interfaces (full JSON array from Agent Card)
    # Format: [{protocolBinding, url, protocolVersion}, ...]
    supported_interfaces = Column(JSON, doc="All supported interfaces array")

    # Source information
    source_type = Column(String(20), nullable=False,
                         doc="Discovery source: url or nacos")

    # For URL mode
    source_url = Column(String(512), doc="Direct URL to agent card")
    agent_card_headers = Column(
        JSON,
        doc="Headers used only to retrieve and refresh the Agent Card"
    )
    ssl_verify = Column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="Verify peer TLS certificates for Agent Card retrieval and A2A invocation",
    )

    # Security declared by the Agent Card and credentials configured by the user
    security_schemes = Column(JSON, doc="Security schemes declared by the Agent Card")
    security_requirements = Column(JSON, doc="Security requirements declared by the Agent Card")
    security_credentials = Column(
        JSON,
        doc="Credential values for Agent Card security schemes, never exposed by APIs"
    )
    selected_security_requirement_index = Column(
        Integer,
        doc="Selected Agent Card security requirement index used for external agent calls"
    )

    # For Nacos mode
    nacos_config_id = Column(
        String(64), doc="Reference to Nacos config used for discovery")
    nacos_agent_name = Column(
        String(255), doc="Original name used for Nacos query")

    # Base URL for infrastructure health checks
    base_url = Column(String(
        512), doc="Base URL for health checks (service root address), e.g., http://agent:8080")

    # Tenant isolation
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)

    # Full original Agent Card
    raw_card = Column(JSON, doc="Full original Agent Card JSON from discovery")

    # Cache management
    cached_at = Column(TIMESTAMP(timezone=False),
                       doc="Timestamp when Agent Card was cached")
    cache_expires_at = Column(
        TIMESTAMP(timezone=False), doc="Timestamp when cache expires")

    # Health check status
    is_available = Column(Boolean, default=True,
                          doc="Whether this agent is currently reachable")
    last_check_at = Column(TIMESTAMP(timezone=False),
                           doc="Last health check timestamp")
    last_check_result = Column(
        String(50), doc="Last health check result: OK, ERROR, TIMEOUT")


class A2AExternalAgentRelation(TableBase):
    """
    Relation between local agent and external A2A agent.
    Enables local agents to call external A2A agents as sub-agents.
    """
    __tablename__ = "ag_a2a_external_agent_relation_t"
    __table_args__ = (
        UniqueConstraint(
            "local_agent_id", "external_agent_id",
            name="uq_local_external_agent",
            deferrable=True,
        ),
        {"schema": SCHEMA},
    )

    id = Column(BigInteger, primary_key=True,
                autoincrement=True, doc=_PRIMARY_KEY_DOC)

    # Local agent (parent)
    local_agent_id = Column(Integer, nullable=False,
                            doc="Local parent agent ID")

    # External A2A agent (sub-agent) - FK to ag_a2a_external_agent_t.id
    external_agent_id = Column(
        BigInteger, nullable=False, doc="External A2A agent ID (FK to ag_a2a_external_agent_t.id)")

    # Tenant isolation
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)

    # Status
    is_enabled = Column(Boolean, default=True,
                        doc="Whether this relation is active")


def active_external_agent_filters(parent_id: int, tenant_id: str):
    relation = A2AExternalAgentRelation
    agent = A2AExternalAgent
    return (
        relation.local_agent_id == parent_id,
        relation.tenant_id == tenant_id,
        relation.delete_flag != "Y",
        relation.is_enabled.is_(True),
        agent.tenant_id == tenant_id,
        agent.delete_flag != "Y",
        agent.is_available.is_(True),
    )


def read_external_agent_bindings(parent_id: int, tenant_id: str, external_ids: list[int]) -> dict[int, dict]:
    """Read only the active external endpoints authorized for the given parent."""
    from infrastructure.rdb.client import get_db_session

    relation = A2AExternalAgentRelation
    agent = A2AExternalAgent
    with get_db_session() as session:
        rows = session.execute(
            select(
                agent.id.label("external_agent_id"), agent.name, agent.description, agent.agent_url,
                agent.ssl_verify, agent.protocol_type, agent.raw_card, agent.security_schemes,
                agent.security_requirements, agent.security_credentials,
            )
            .join(relation, relation.external_agent_id == agent.id)
            .where(*active_external_agent_filters(parent_id, tenant_id), agent.id.in_(external_ids))
        ).mappings()
        return {row["external_agent_id"]: dict(row) for row in rows}
