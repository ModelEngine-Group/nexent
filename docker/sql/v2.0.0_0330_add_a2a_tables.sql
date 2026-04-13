-- A2A Protocol Tables Migration
-- Purpose: Support A2A (Agent-to-Agent) protocol with both Client (discover and call external agents) and Server (expose local agents) capabilities
-- Tables created:
--   1. ag_a2a_nacos_config_t - Nacos configuration for external A2A agent discovery
--   2. ag_a2a_external_agent_t - External A2A agents discovered from URL or Nacos
--   3. ag_a2a_external_agent_relation_t - Relation between local agent and external A2A agent
--   4. ag_a2a_server_agent_t - Local agents registered as A2A Server endpoints
--   5. ag_a2a_task_t - A2A tasks for tracking requests
--   6. ag_a2a_message_t - A2A messages within tasks

-- =============================================================================
-- Table 1: ag_a2a_nacos_config_t
-- Purpose: Store Nacos server configuration for external A2A agent discovery
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_nacos_config_t (
    id BIGSERIAL PRIMARY KEY,
    config_id VARCHAR(64) UNIQUE NOT NULL,

    -- Nacos connection
    nacos_addr VARCHAR(512) NOT NULL,
    nacos_username VARCHAR(100),
    nacos_password VARCHAR(256),

    -- Discovery scope
    namespace_id VARCHAR(100) DEFAULT 'public',

    -- Metadata
    name VARCHAR(100) NOT NULL,
    description TEXT,

    -- Tenant isolation
    tenant_id VARCHAR(100) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100),

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    last_scan_at TIMESTAMP(6),

    -- Audit
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_a2a_nacos_config_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_nacos_config_t IS 'Nacos configuration for external A2A agent discovery. Stores connection info and discovery scope.';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.id IS 'Primary key, auto-increment';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.config_id IS 'Unique config identifier for API reference';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.nacos_addr IS 'Nacos server address, e.g., http://nacos-server:8848';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.nacos_username IS 'Nacos username for authentication';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.nacos_password IS 'Nacos password, encrypted at rest';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.namespace_id IS 'Nacos namespace for service discovery, default is public';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.name IS 'Display name for this Nacos config, e.g., Production Nacos';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.description IS 'Description of this Nacos configuration';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.tenant_id IS 'Tenant ID for multi-tenancy isolation';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.created_by IS 'User who created this config';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.updated_by IS 'User who last updated this record';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.is_active IS 'Whether this Nacos config is active';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.last_scan_at IS 'Last time a scan was performed using this config';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.create_time IS 'Record creation timestamp';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.update_time IS 'Record last update timestamp';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.delete_flag IS 'Soft delete flag: Y/N';

-- =============================================================================
-- Table 2: ag_a2a_external_agent_t
-- Purpose: Cache external A2A agents discovered from URL or Nacos
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_external_agent_t (
    id BIGSERIAL PRIMARY KEY,

    -- Agent metadata (cached from Agent Card)
    name VARCHAR(255) NOT NULL,
    description TEXT,
    version VARCHAR(50),

    -- Primary interface (extracted from supportedInterfaces for quick access)
    agent_url VARCHAR(512) NOT NULL,

    -- Protocol type for calling this agent
    -- Values: 'JSONRPC' (JSON-RPC 2.0), 'HTTP+JSON' (HTTP+JSON REST), 'GRPC'
    protocol_type VARCHAR(20) DEFAULT 'JSONRPC',

    -- Capabilities
    streaming BOOLEAN DEFAULT FALSE,

    -- All supported interfaces (full JSON array from Agent Card)
    -- Format: [{protocolBinding, url, protocolVersion}, ...]
    supported_interfaces JSONB,

    -- Source information
    source_type VARCHAR(20) NOT NULL,

    -- For URL mode:
    source_url VARCHAR(512),

    -- For Nacos mode:
    nacos_config_id VARCHAR(64),
    nacos_agent_name VARCHAR(255),

    -- Tenant isolation
    tenant_id VARCHAR(100) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100),

    -- Full original Agent Card
    raw_card JSONB,

    -- Cache management
    cached_at TIMESTAMP(6),
    cache_expires_at TIMESTAMP(6),

    -- Health check status
    is_available BOOLEAN DEFAULT TRUE,
    last_check_at TIMESTAMP(6),
    last_check_result VARCHAR(50),

    -- Audit
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_a2a_external_agent_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_external_agent_t IS 'External A2A agents discovered from URL or Nacos. Caches Agent Cards for A2A Client role.';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.id IS 'Primary key, auto-increment. Used as unique identifier for internal references.';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.name IS 'Agent name from Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.description IS 'Agent description from Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.version IS 'Agent version from Agent Card, e.g., 1.2.0';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.agent_url IS 'Primary A2A endpoint URL (http-json-rpc by default, extracted from supportedInterfaces)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.protocol_type IS 'Protocol type for calling this agent: JSONRPC, HTTP+JSON, or GRPC';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.streaming IS 'Whether this agent supports SSE streaming (from capabilities.streaming)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.supported_interfaces IS 'All supported interfaces array from Agent Card. Format: [{protocolBinding, url, protocolVersion}, ...]';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.source_type IS 'Discovery source: url or nacos';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.source_url IS 'Direct URL to agent card (for url source type)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.nacos_config_id IS 'Reference to Nacos config used for discovery (for nacos source type)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.nacos_agent_name IS 'Original name used for Nacos query';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.tenant_id IS 'Tenant ID for multi-tenancy isolation';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.created_by IS 'User who discovered this agent';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.updated_by IS 'User who last updated this record';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.raw_card IS 'Full original Agent Card JSON from discovery';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.cached_at IS 'Timestamp when Agent Card was cached';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.cache_expires_at IS 'Timestamp when cache expires';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.is_available IS 'Whether this agent is currently reachable';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.last_check_at IS 'Last health check timestamp';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.last_check_result IS 'Last health check result: OK, ERROR, TIMEOUT';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.create_time IS 'Record creation timestamp';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.update_time IS 'Record last update timestamp';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.delete_flag IS 'Soft delete flag: Y/N';

-- =============================================================================
-- Table 3: ag_a2a_external_agent_relation_t
-- Purpose: Relation between local agent and external A2A agent (sub-agent relationship)
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_external_agent_relation_t (
    id BIGSERIAL PRIMARY KEY,

    -- Local agent (parent)
    local_agent_id INTEGER NOT NULL,

    -- External A2A agent (sub-agent) - FK to ag_a2a_external_agent_t.id
    external_agent_id BIGINT NOT NULL,

    -- Tenant isolation
    tenant_id VARCHAR(100) NOT NULL,

    -- Status
    is_enabled BOOLEAN DEFAULT TRUE,

    -- Audit
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100),
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N',

    -- Constraints
    CONSTRAINT uq_local_external_agent UNIQUE (local_agent_id, external_agent_id),
    CONSTRAINT fk_external_agent FOREIGN KEY (external_agent_id) REFERENCES nexent.ag_a2a_external_agent_t(id)
);

ALTER TABLE nexent.ag_a2a_external_agent_relation_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_external_agent_relation_t IS 'Relation between local agent and external A2A agent. Enables local agents to call external A2A agents as sub-agents.';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.id IS 'Primary key, auto-increment';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.local_agent_id IS 'Local parent agent ID (FK to ag_tenant_agent_t)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.external_agent_id IS 'External A2A agent ID (FK to ag_a2a_external_agent_t.id)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.tenant_id IS 'Tenant ID for multi-tenancy isolation';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.is_enabled IS 'Whether this relation is active';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.created_by IS 'User who created this relation';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.updated_by IS 'User who last updated this record';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.create_time IS 'Record creation timestamp';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.update_time IS 'Record last update timestamp';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.delete_flag IS 'Soft delete flag: Y/N';

-- =============================================================================
-- Table 4: ag_a2a_server_agent_t
-- Purpose: Local agents registered as A2A Server endpoints
-- A2A Agent Card fields exposed to external callers
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_server_agent_t (
    id BIGSERIAL PRIMARY KEY,

    -- Link to local agent
    agent_id INTEGER NOT NULL,

    -- Ownership (required for tenant isolation)
    user_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),

    -- Generated endpoint ID (unique, used for A2A routing)
    endpoint_id VARCHAR(64) UNIQUE NOT NULL,

    -- ============================================
    -- A2A 1.0 Agent Card Fields (exposed to callers)
    -- ============================================

    -- Basic info (extracted from local agent, can be overridden)
    name VARCHAR(255) NOT NULL,
    description TEXT,
    version VARCHAR(50),

    -- Primary endpoint URL (http-json-rpc by default)
    agent_url VARCHAR(512),

    -- Capabilities
    streaming BOOLEAN DEFAULT FALSE,

    -- All supported interfaces (A2A 1.0 compliant)
    -- Format: [{protocolBinding, url, protocolVersion}, ...]
    supported_interfaces JSONB,

    -- Agent Card customization (partial overrides only)
    card_overrides JSONB,

    -- ============================================
    -- Server-specific settings
    -- ============================================

    -- A2A Server status
    is_enabled BOOLEAN DEFAULT FALSE,

    -- Raw Agent Card (generated from settings, for debugging)
    raw_card JSONB,

    -- Publishing timestamps
    published_at TIMESTAMP(6),
    unpublished_at TIMESTAMP(6),

    response_format VARCHAR(20) DEFAULT 'task',

    -- Audit
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_a2a_server_agent_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_server_agent_t IS 'Local agents registered as A2A Server endpoints. Exposes Agent Cards for external A2A callers.';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.id IS 'Primary key, auto-increment';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.agent_id IS 'Local agent ID (FK to ag_tenant_agent_t)';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.user_id IS 'Owner user ID';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.tenant_id IS 'Tenant ID for multi-tenancy isolation';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.created_by IS 'User who created this A2A Server agent';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.updated_by IS 'User who last updated this A2A Server agent';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.endpoint_id IS 'Generated endpoint ID, format: a2a_{agent_id[:8]}_{hash[:8]}';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.name IS 'Agent name exposed in Agent Card (from agent or override)';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.description IS 'Agent description exposed in Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.version IS 'Agent version exposed in Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.agent_url IS 'Primary A2A endpoint URL (http-json-rpc by default)';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.streaming IS 'Whether this agent supports SSE streaming';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.supported_interfaces IS 'All supported interfaces: [{protocolBinding, url, protocolVersion}, ...]';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.card_overrides IS 'User customizations for Agent Card (partial override)';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.is_enabled IS 'Whether A2A Server is enabled for this agent';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.raw_card IS 'Generated Agent Card JSON (for debugging)';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.published_at IS 'Timestamp when A2A Server was last enabled';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.unpublished_at IS 'Timestamp when A2A Server was disabled';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.create_time IS 'Record creation timestamp';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.update_time IS 'Record last update timestamp';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.delete_flag IS 'Soft delete flag: Y/N';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.response_format IS 'Response format: ''task'' for full Task response, ''message'' for simple Message response';


-- =============================================================================
-- Table 5: ag_a2a_task_t
-- Purpose: A2A tasks for tracking requests (Server side)
-- Note: Task is the unit of work, not all requests need to create a task.
--       Simple requests can return Message directly without creating a Task record.
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_task_t (
    -- Core identifiers (following A2A spec)
    id VARCHAR(64) PRIMARY KEY,                      -- taskId
    context_id VARCHAR(64),                          -- contextId

    -- Endpoint and caller info
    endpoint_id VARCHAR(64) NOT NULL,
    caller_user_id VARCHAR(100),
    caller_tenant_id VARCHAR(100),

    -- Request data
    raw_request JSONB,

    -- Task state (following A2A TaskState enum)
    task_state VARCHAR(50) NOT NULL DEFAULT 'TASK_STATE_SUBMITTED',
    state_timestamp TIMESTAMP(6),                    -- State update timestamp

    -- Task result
    result_data JSONB,                              -- Final result (renamed from result to avoid SQL function conflict)

    -- Timestamps
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP(6)
);

ALTER TABLE nexent.ag_a2a_task_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_task_t IS 'A2A tasks for tracking requests. Task is the unit of work, not all requests need to create a task.';
COMMENT ON COLUMN nexent.ag_a2a_task_t.id IS 'Task ID from A2A protocol, primary key';
COMMENT ON COLUMN nexent.ag_a2a_task_t.context_id IS 'Context ID for grouping related A2A tasks';
COMMENT ON COLUMN nexent.ag_a2a_task_t.endpoint_id IS 'Endpoint ID (FK to ag_a2a_server_agent_t.endpoint_id)';
COMMENT ON COLUMN nexent.ag_a2a_task_t.caller_user_id IS 'User ID of the caller (for audit)';
COMMENT ON COLUMN nexent.ag_a2a_task_t.caller_tenant_id IS 'Tenant ID of the caller (for audit)';
COMMENT ON COLUMN nexent.ag_a2a_task_t.raw_request IS 'Original A2A request payload';
COMMENT ON COLUMN nexent.ag_a2a_task_t.task_state IS 'Task state: TASK_STATE_SUBMITTED, TASK_STATE_WORKING, TASK_STATE_COMPLETED, TASK_STATE_FAILED, TASK_STATE_CANCELED, TASK_STATE_INPUT_REQUIRED, TASK_STATE_REJECTED, TASK_STATE_AUTH_REQUIRED';
COMMENT ON COLUMN nexent.ag_a2a_task_t.state_timestamp IS 'Task state last update timestamp';
COMMENT ON COLUMN nexent.ag_a2a_task_t.result_data IS 'Task final result data';
COMMENT ON COLUMN nexent.ag_a2a_task_t.create_time IS 'Task creation timestamp';
COMMENT ON COLUMN nexent.ag_a2a_task_t.update_time IS 'Task last update timestamp';
COMMENT ON COLUMN nexent.ag_a2a_task_t.completed_at IS 'Task completion timestamp';

-- =============================================================================
-- Table 6: ag_a2a_message_t
-- Purpose: A2A messages within tasks (Task history)
-- Note: Stores conversation history for multi-turn interactions.
--       Supports both task-based (complex requests) and standalone (simple requests) storage.
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_message_t (
    -- Core identifiers (following A2A spec)
    message_id VARCHAR(64) PRIMARY KEY,              -- messageId (A2A spec naming)
    task_id VARCHAR(64),                            -- taskId (associated task), can be NULL for simple requests

    -- Message attributes
    message_index INTEGER NOT NULL,                  -- Sequence index
    role VARCHAR(20) NOT NULL CHECK (role IN ('ROLE_UNSPECIFIED', 'ROLE_USER', 'ROLE_AGENT')),  -- Following A2A spec: ROLE_UNSPECIFIED, ROLE_USER, ROLE_AGENT

    -- Message content (following A2A Part structure)
    parts JSONB NOT NULL,                            -- Part array
    meta_data JSONB,                                  -- Optional metadata
    extensions JSONB,                               -- Extension URI list

    -- References to other tasks (optional)
    reference_task_ids JSONB,                        -- Referenced task IDs array

    -- Timestamp
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    -- Partial unique constraint for non-NULL task_id values
    -- Allows multiple NULL task_id rows (simple requests without Task)
    UNIQUE(task_id, message_index)
);

ALTER TABLE nexent.ag_a2a_message_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_message_t IS 'A2A messages within tasks. Stores conversation history for multi-turn interactions.';
COMMENT ON COLUMN nexent.ag_a2a_message_t.message_id IS 'Message ID, primary key (A2A spec: messageId)';
COMMENT ON COLUMN nexent.ag_a2a_message_t.task_id IS 'Task ID this message belongs to (FK to ag_a2a_task_t.id), can be NULL for simple requests without Task';
COMMENT ON COLUMN nexent.ag_a2a_message_t.message_index IS 'Order of message in the conversation';
COMMENT ON COLUMN nexent.ag_a2a_message_t.role IS 'Message sender role: ROLE_UNSPECIFIED, ROLE_USER, or ROLE_AGENT';
COMMENT ON COLUMN nexent.ag_a2a_message_t.parts IS 'Message parts following A2A Part structure: [{"type": "text", "text": "..."}]';
COMMENT ON COLUMN nexent.ag_a2a_message_t.meta_data IS 'Optional message metadata';
COMMENT ON COLUMN nexent.ag_a2a_message_t.extensions IS 'Extension URI list';
COMMENT ON COLUMN nexent.ag_a2a_message_t.reference_task_ids IS 'Referenced task IDs array for multi-turn scenarios';
COMMENT ON COLUMN nexent.ag_a2a_message_t.create_time IS 'Message creation timestamp';

-- =============================================================================
-- Table 7: ag_a2a_artifact_t
-- Purpose: A2A artifacts (task outputs)
-- Note: Stores the output/artifacts produced by a task.
--       Artifact must be associated with a Task (no standalone artifacts).
-- =============================================================================
CREATE TABLE IF NOT EXISTS nexent.ag_a2a_artifact_t (
    -- Core identifiers (following A2A spec)
    id VARCHAR(64) PRIMARY KEY,                      -- Internal primary key
    artifact_id VARCHAR(64) NOT NULL,                 -- artifactId (A2A spec naming)
    task_id VARCHAR(64) NOT NULL,                    -- taskId (associated task, required)

    -- Artifact attributes
    name VARCHAR(255),                               -- Human-readable name
    description TEXT,                               -- Description
    parts JSONB NOT NULL,                           -- Part array (following A2A spec)
    metadata JSONB,                                  -- Metadata
    extensions JSONB,                                -- Extension URI list

    -- Timestamp
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    -- Foreign key constraint
    CONSTRAINT fk_artifact_task FOREIGN KEY (task_id)
        REFERENCES nexent.ag_a2a_task_t(id) ON DELETE CASCADE,
    UNIQUE(task_id, artifact_id)
);

ALTER TABLE nexent.ag_a2a_artifact_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_artifact_t IS 'A2A artifacts. Stores the output/artifacts produced by a task.';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.id IS 'Internal primary key';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.artifact_id IS 'Artifact ID (A2A spec: artifactId)';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.task_id IS 'Task ID this artifact belongs to (FK to ag_a2a_task_t.id), required - no standalone artifacts';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.name IS 'Human-readable artifact name';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.description IS 'Artifact description';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.parts IS 'Artifact parts following A2A Part structure: [{"type": "text", "text": "..."}]';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.metadata IS 'Artifact metadata';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.extensions IS 'Extension URI list';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.create_time IS 'Artifact creation timestamp';
