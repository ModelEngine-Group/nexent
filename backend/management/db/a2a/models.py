# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    BigInteger,
    Boolean,
    Column,
    Integer,
    String,
    Text,
    UniqueConstraint,
)


from sqlalchemy.sql import func


from management.db.base import PROTOCOL_JSONRPC, SCHEMA, SimpleTableBase, TableBase, _PRIMARY_KEY_DOC, _TENANT_ID_DOC


class A2ANacosConfig(TableBase):
    """
    Nacos configuration for external A2A agent discovery.
    Stores connection info and discovery scope.
    """
    __tablename__ = "ag_a2a_nacos_config_t"
    __table_args__ = {"schema": SCHEMA}

    id = Column(BigInteger, primary_key=True,
                autoincrement=True, doc=_PRIMARY_KEY_DOC)
    config_id = Column(String(64), unique=True, nullable=False,
                       doc="Unique config identifier for API reference")

    # Nacos connection
    nacos_addr = Column(String(512), nullable=False,
                        doc="Nacos server address, e.g., http://nacos-server:8848")
    nacos_username = Column(
        String(100), doc="Nacos username for authentication")
    nacos_password = Column(
        String(256), doc="Nacos password, encrypted at rest")

    # Discovery scope
    namespace_id = Column(String(100), default="public",
                          doc="Nacos namespace for service discovery")

    # Metadata
    name = Column(String(100), nullable=False,
                  doc="Display name for this Nacos config")
    description = Column(Text, doc="Description of this Nacos configuration")

    # Tenant isolation
    tenant_id = Column(String(100), nullable=False,
                       doc="Tenant ID for multi-tenancy")

    # Status
    is_active = Column(Boolean, default=True,
                       doc="Whether this Nacos config is active")
    last_scan_at = Column(TIMESTAMP(timezone=False),
                          doc="Last time a scan was performed using this config")


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


class A2AServerAgent(TableBase):
    """
    Local agents registered as A2A Server endpoints.
    Exposes Agent Cards for external A2A callers.
    """
    __tablename__ = "ag_a2a_server_agent_t"
    __table_args__ = {"schema": SCHEMA}

    id = Column(BigInteger, primary_key=True,
                autoincrement=True, doc=_PRIMARY_KEY_DOC)

    # Link to local agent
    agent_id = Column(Integer, nullable=False, doc="Local agent ID")

    # Ownership
    user_id = Column(String(100), nullable=False, doc="Owner user ID")
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)

    # Generated endpoint ID
    endpoint_id = Column(String(64), unique=True,
                         nullable=False, doc="Generated endpoint ID")

    # Basic info (extracted from local agent, can be overridden)
    name = Column(String(255), nullable=False,
                  doc="Agent name exposed in Agent Card")
    description = Column(Text, doc="Agent description exposed in Agent Card")
    version = Column(String(50), doc="Agent version exposed in Agent Card")

    # Primary endpoint URL (http-json-rpc by default)
    agent_url = Column(
        String(512), doc="Primary A2A endpoint URL (http-json-rpc by default)")

    # Capabilities
    streaming = Column(Boolean, default=False,
                       doc="Whether this agent supports SSE streaming")

    # All supported interfaces (A2A 1.0 compliant)
    # Format: [{protocolBinding, url, protocolVersion}, ...]
    supported_interfaces = Column(
        JSON, doc="All supported interfaces: [{protocolBinding, url, protocolVersion}, ...]")

    # Agent Card customization (partial overrides only)
    card_overrides = Column(
        JSON, doc="User customizations for Agent Card (partial override)")

    # A2A Server status
    is_enabled = Column(Boolean, default=False,
                        doc="Whether A2A Server is enabled for this agent")

    # Raw Agent Card (generated from settings, for debugging)
    raw_card = Column(JSON, doc="Generated Agent Card JSON (for debugging)")

    # Publishing timestamps
    published_at = Column(TIMESTAMP(timezone=False),
                          doc="Timestamp when A2A Server was last enabled")
    unpublished_at = Column(TIMESTAMP(timezone=False),
                            doc="Timestamp when A2A Server was disabled")


class A2ATask(SimpleTableBase):
    """
    A2A tasks for tracking requests.
    Task is the unit of work, not all requests need to create a task.
    """
    __tablename__ = "ag_a2a_task_t"
    __table_args__ = {"schema": SCHEMA}

    # Core identifiers (following A2A spec)
    id = Column(String(64), primary_key=True, doc="Task ID (A2A spec: taskId)")
    context_id = Column(
        String(64), doc="Context ID for grouping related tasks")

    # Endpoint and caller info
    endpoint_id = Column(String(64), nullable=False, doc="Endpoint ID")
    caller_user_id = Column(String(100), doc="User ID of the caller")
    caller_tenant_id = Column(String(100), doc="Tenant ID of the caller")

    # Request data
    raw_request = Column(JSON, doc="Original A2A request payload")

    # Task state (following A2A TaskState enum)
    task_state = Column(String(50), nullable=False, server_default="TASK_STATE_SUBMITTED",
                        doc="Task state: TASK_STATE_SUBMITTED, TASK_STATE_WORKING, TASK_STATE_COMPLETED, TASK_STATE_FAILED, TASK_STATE_CANCELED, TASK_STATE_INPUT_REQUIRED, TASK_STATE_REJECTED, TASK_STATE_AUTH_REQUIRED")
    state_timestamp = Column(TIMESTAMP(timezone=False),
                             doc="Task state last update timestamp")

    # Task result
    result_data = Column(JSON, doc="Task final result data")

    # Timestamps
    create_time = Column(TIMESTAMP(timezone=False),
                         server_default=func.now(), doc="Task creation timestamp")
    update_time = Column(TIMESTAMP(timezone=False), server_default=func.now(
    ), onupdate=func.now(), doc="Task last update timestamp")
    completed_at = Column(TIMESTAMP(timezone=False),
                          doc="Task completion timestamp")


class A2AMessage(SimpleTableBase):
    """
    A2A messages within tasks.
    Stores conversation history for multi-turn interactions.
    """
    __tablename__ = "ag_a2a_message_t"
    __table_args__ = {"schema": SCHEMA}

    # Core identifiers (following A2A spec)
    message_id = Column(String(64), primary_key=True,
                        doc="Message ID (A2A spec: messageId)")
    task_id = Column(String(64), nullable=True,
                     doc="Task ID this message belongs to (nullable for standalone/simple requests)")

    # Message attributes
    message_index = Column(Integer, nullable=False,
                           doc="Order of message in the conversation")
    role = Column(String(20), nullable=False,
                  doc="Message sender role: user or agent")

    # Message content (following A2A Part structure)
    parts = Column(JSON, nullable=False,
                   doc="Message parts following A2A Part structure")
    meta_data = Column(JSON, doc="Optional metadata")
    extensions = Column(JSON, doc="Extension URI list")

    # References to other tasks (optional)
    reference_task_ids = Column(
        JSON, doc="Referenced task IDs array for multi-turn scenarios")

    # Timestamp
    create_time = Column(TIMESTAMP(
        timezone=False), server_default=func.now(), doc="Message creation timestamp")


class A2AArtifact(SimpleTableBase):
    """
    A2A artifacts. Stores the output/artifacts produced by a task.
    """
    __tablename__ = "ag_a2a_artifact_t"
    __table_args__ = {"schema": SCHEMA}

    # Core identifiers (following A2A spec)
    id = Column(String(64), primary_key=True, doc="Internal primary key")
    artifact_id = Column(String(64), nullable=False,
                         doc="Artifact ID (A2A spec: artifactId)")
    task_id = Column(String(64), nullable=False,
                     doc="Task ID this artifact belongs to")

    # Artifact attributes
    name = Column(String(255), doc="Human-readable artifact name")
    description = Column(Text, doc="Artifact description")
    parts = Column(JSON, nullable=False,
                   doc="Artifact parts following A2A Part structure")
    meta_data = Column(JSON, doc="Artifact metadata")
    extensions = Column(JSON, doc="Extension URI list")

    # Timestamp
    create_time = Column(TIMESTAMP(timezone=False), server_default=func.now(), doc="Artifact creation timestamp")
