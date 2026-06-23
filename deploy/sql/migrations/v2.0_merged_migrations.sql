-- Nexent merged SQL migrations: v2.0
-- This file is generated from historical migration files.
-- Keep each nexent-migration-source marker when editing.

-- nexent-migration-source: v2.0.0_0314_add_context_skill_t.sql
-- nexent-migration-checksum: efe07c8063bf76add73fd8516455a941080d807291d4d21aa656239f312faf3d
-- nexent-migration-probe: SELECT to_regclass('nexent.ag_skill_info_t') IS NOT NULL AND to_regclass('nexent.ag_skill_instance_t') IS NOT NULL;
-- Migration: Add ag_skill_info_t, ag_skill_tools_rel_t, and ag_skill_instance_t tables
-- Date: 2026-03-14
-- Description: Create skill management tables with skill content, tags, and tool relationships

SET search_path TO nexent;

-- Create the ag_skill_info_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.ag_skill_info_t (
    skill_id SERIAL4 PRIMARY KEY NOT NULL,
    skill_name VARCHAR(100) NOT NULL,
    skill_description VARCHAR(1000),
    skill_tags JSON,
    skill_content TEXT,
    params JSON,
    source VARCHAR(30) DEFAULT 'official',
    created_by VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE "ag_skill_info_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.ag_skill_info_t IS 'Skill information table for managing custom skills';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_id IS 'Skill ID, unique primary key';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_name IS 'Skill name, globally unique';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_description IS 'Skill description text';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_tags IS 'Skill tags stored as JSON array';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_content IS 'Skill content or prompt text';
COMMENT ON COLUMN nexent.ag_skill_info_t.params IS 'Skill configuration parameters stored as JSON object';
COMMENT ON COLUMN nexent.ag_skill_info_t.source IS 'Skill source: official, custom, or partner';
COMMENT ON COLUMN nexent.ag_skill_info_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.ag_skill_info_t.create_time IS 'Creation timestamp';
COMMENT ON COLUMN nexent.ag_skill_info_t.updated_by IS 'Last updater ID';
COMMENT ON COLUMN nexent.ag_skill_info_t.update_time IS 'Last update timestamp';
COMMENT ON COLUMN nexent.ag_skill_info_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create the ag_skill_tools_rel_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.ag_skill_tools_rel_t (
    rel_id SERIAL4 PRIMARY KEY NOT NULL,
    skill_id INTEGER,
    tool_id INTEGER,
    created_by VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE "ag_skill_tools_rel_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.ag_skill_tools_rel_t IS 'Skill-tool relationship table for many-to-many mapping';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.rel_id IS 'Relationship ID, unique primary key';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.skill_id IS 'Foreign key to ag_skill_info_t.skill_id';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.tool_id IS 'Tool ID from ag_tool_info_t';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.create_time IS 'Creation timestamp';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.updated_by IS 'Last updater ID';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.update_time IS 'Last update timestamp';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create the ag_skill_instance_t table in the nexent schema
-- Stores skill instance configuration per agent version
-- Note: skill_description and skill_content fields removed, now retrieved from ag_skill_info_t
CREATE TABLE IF NOT EXISTS nexent.ag_skill_instance_t (
    skill_instance_id SERIAL4 NOT NULL,
    skill_id INTEGER NOT NULL,
    agent_id INTEGER NOT NULL,
    user_id VARCHAR(100),
    tenant_id VARCHAR(100),
    enabled BOOLEAN DEFAULT TRUE,
    version_no INTEGER DEFAULT 0 NOT NULL,
    created_by VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT ag_skill_instance_t_pkey PRIMARY KEY (skill_instance_id, version_no)
);

ALTER TABLE "ag_skill_instance_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.ag_skill_instance_t IS 'Skill instance configuration table - stores per-agent skill settings';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_skill_instance_t.skill_instance_id IS 'Skill instance ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.skill_id IS 'Foreign key to ag_skill_info_t.skill_id';
COMMENT ON COLUMN nexent.ag_skill_instance_t.agent_id IS 'Agent ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.enabled IS 'Whether this skill is enabled for the agent';
COMMENT ON COLUMN nexent.ag_skill_instance_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';
COMMENT ON COLUMN nexent.ag_skill_instance_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.create_time IS 'Creation timestamp';
COMMENT ON COLUMN nexent.ag_skill_instance_t.updated_by IS 'Last updater ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.update_time IS 'Last update timestamp';
COMMENT ON COLUMN nexent.ag_skill_instance_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- nexent-migration-source: v2.0.1_0331_add_outer_api_tool_t.sql
-- nexent-migration-checksum: ac18655659eac2a8d155cd7188870f55aa27795f5e27a6f77a2b33fda5a005d5
-- nexent-migration-probe: SELECT to_regclass('nexent.ag_outer_api_tools') IS NOT NULL OR to_regclass('nexent.ag_outer_api_services') IS NOT NULL;
-- v2.0.1_0331_add_outer_api_tool_t.sql
-- Create table for outer API tools (OpenAPI to MCP conversion)

-- Create the ag_outer_api_tools table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.ag_outer_api_tools (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    method VARCHAR(10),
    url TEXT NOT NULL,
    headers_template JSONB DEFAULT '{}',
    query_template JSONB DEFAULT '{}',
    body_template JSONB DEFAULT '{}',
    input_schema JSONB DEFAULT '{}',
    tenant_id VARCHAR(100),
    is_available BOOLEAN DEFAULT TRUE,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_outer_api_tools OWNER TO "root";

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_ag_outer_api_tools_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create a trigger to call the function before each update
CREATE TRIGGER update_ag_outer_api_tools_update_time_trigger
BEFORE UPDATE ON nexent.ag_outer_api_tools
FOR EACH ROW
EXECUTE FUNCTION update_ag_outer_api_tools_update_time();

-- Add comment to the table
COMMENT ON TABLE nexent.ag_outer_api_tools IS 'Outer API tools table - stores converted OpenAPI tools as MCP tools';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_outer_api_tools.id IS 'Tool ID, unique primary key';
COMMENT ON COLUMN nexent.ag_outer_api_tools.name IS 'Tool name (unique identifier)';
COMMENT ON COLUMN nexent.ag_outer_api_tools.description IS 'Tool description';
COMMENT ON COLUMN nexent.ag_outer_api_tools.method IS 'HTTP method: GET/POST/PUT/DELETE/PATCH';
COMMENT ON COLUMN nexent.ag_outer_api_tools.url IS 'API endpoint URL (full path with base URL)';
COMMENT ON COLUMN nexent.ag_outer_api_tools.headers_template IS 'Headers template as JSONB';
COMMENT ON COLUMN nexent.ag_outer_api_tools.query_template IS 'Query parameters template as JSONB';
COMMENT ON COLUMN nexent.ag_outer_api_tools.body_template IS 'Request body template as JSONB';
COMMENT ON COLUMN nexent.ag_outer_api_tools.input_schema IS 'MCP input schema as JSONB';
COMMENT ON COLUMN nexent.ag_outer_api_tools.tenant_id IS 'Tenant ID for multi-tenancy';
COMMENT ON COLUMN nexent.ag_outer_api_tools.is_available IS 'Whether the tool is available';
COMMENT ON COLUMN nexent.ag_outer_api_tools.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_outer_api_tools.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_outer_api_tools.created_by IS 'Creator';
COMMENT ON COLUMN nexent.ag_outer_api_tools.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.ag_outer_api_tools.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create index for tenant_id queries
CREATE INDEX IF NOT EXISTS idx_ag_outer_api_tools_tenant_id
ON nexent.ag_outer_api_tools (tenant_id)
WHERE delete_flag = 'N';

-- Create index for name queries
CREATE INDEX IF NOT EXISTS idx_ag_outer_api_tools_name
ON nexent.ag_outer_api_tools (name)
WHERE delete_flag = 'N';

-- nexent-migration-source: v2.0.2_0410_add_columns_outer_api_tools.sql
-- nexent-migration-checksum: db16813121a1ba74ec3e7f2d925b4412e4026a986b2e66ce0cd3b11691ae3771
-- nexent-migration-probe: SELECT to_regclass('nexent.ag_outer_api_services') IS NOT NULL OR EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'ag_outer_api_tools' AND column_name = 'mcp_service_name');
-- v2.0.2_0410_add_columns_outer_api_tools.sql
-- Add MCP service-level columns to ag_outer_api_tools table
-- These columns enable grouping tools from the same OpenAPI spec under a single MCP service

-- Add columns for MCP service information
ALTER TABLE nexent.ag_outer_api_tools
    ADD COLUMN IF NOT EXISTS mcp_service_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS openapi_json JSONB,
    ADD COLUMN IF NOT EXISTS server_url VARCHAR(500);

-- Add comments to the new columns
COMMENT ON COLUMN nexent.ag_outer_api_tools.mcp_service_name IS 'MCP service name for grouping tools from same OpenAPI spec';
COMMENT ON COLUMN nexent.ag_outer_api_tools.openapi_json IS 'Complete OpenAPI JSON specification';
COMMENT ON COLUMN nexent.ag_outer_api_tools.server_url IS 'Base URL of the REST API server';

-- Create index for mcp_service_name queries
CREATE INDEX IF NOT EXISTS idx_ag_outer_api_tools_mcp_service_name
ON nexent.ag_outer_api_tools (mcp_service_name)
WHERE delete_flag = 'N' AND mcp_service_name IS NOT NULL;

-- nexent-migration-source: v2.0.2_0414_add_a2a_tables.sql
-- nexent-migration-checksum: a9e31d201a969ab358e75fd8c51153d11b1acddaab5171a80d9f0eefe10a5df5
-- nexent-migration-probe: SELECT to_regclass('nexent.ag_a2a_nacos_config_t') IS NOT NULL AND to_regclass('nexent.ag_a2a_message_t') IS NOT NULL AND to_regclass('nexent.ag_a2a_artifact_t') IS NOT NULL;
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
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.id IS 'Primary key, auto-increment'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.config_id IS 'Unique config identifier for API reference';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.nacos_addr IS 'Nacos server address, e.g., http://nacos-server:8848';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.nacos_username IS 'Nacos username for authentication';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.nacos_password IS 'Nacos password, encrypted at rest';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.namespace_id IS 'Nacos namespace for service discovery, default is public';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.name IS 'Display name for this Nacos config, e.g., Production Nacos';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.description IS 'Description of this Nacos configuration';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.tenant_id IS 'Tenant ID for multi-tenancy isolation'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.created_by IS 'User who created this config';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.updated_by IS 'User who last updated this record'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.is_active IS 'Whether this Nacos config is active';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.last_scan_at IS 'Last time a scan was performed using this config';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.create_time IS 'Record creation timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.update_time IS 'Record last update timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.delete_flag IS 'Soft delete flag: Y/N';  -- NOSONAR

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
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.delete_flag IS 'Soft delete flag: Y/N'; -- NOSONAR

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
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.id IS 'Primary key, auto-increment';  -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.local_agent_id IS 'Local parent agent ID (FK to ag_tenant_agent_t)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.external_agent_id IS 'External A2A agent ID (FK to ag_a2a_external_agent_t.id)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.tenant_id IS 'Tenant ID for multi-tenancy isolation'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.is_enabled IS 'Whether this relation is active';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.created_by IS 'User who created this relation';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.updated_by IS 'User who last updated this record'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.create_time IS 'Record creation timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.update_time IS 'Record last update timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.delete_flag IS 'Soft delete flag: Y/N';  -- NOSONAR

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
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.id IS 'Primary key, auto-increment';  -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.agent_id IS 'Local agent ID (FK to ag_tenant_agent_t)';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.user_id IS 'Owner user ID';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.tenant_id IS 'Tenant ID for multi-tenancy isolation'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.created_by IS 'User who created this A2A Server agent';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.updated_by IS 'User who last updated this A2A Server agent'; -- NOSONAR
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
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.create_time IS 'Record creation timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.update_time IS 'Record last update timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.delete_flag IS 'Soft delete flag: Y/N'; -- NOSONAR
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
    meta_data JSONB,                                -- Metadata
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
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.meta_data IS 'Artifact metadata';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.extensions IS 'Extension URI list';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.create_time IS 'Artifact creation timestamp';

-- nexent-migration-source: v2.0.2_0414_migrate_outer_api_tools_to_services.sql
-- nexent-migration-checksum: cab21c537fe3341ef825eae574cc0c16797770e3d6a730c6bddd0fa1a306d0ab
-- nexent-migration-probe: SELECT to_regclass('nexent.ag_outer_api_services') IS NOT NULL AND to_regclass('nexent.ag_outer_api_tools') IS NULL;
-- Migration: Convert ag_outer_api_tools (tool-level) to ag_outer_api_services (service-level)
-- Date: 2026-04-09
-- Description: Each OpenAPI service now stores one record instead of one record per tool.
--             Only service-level fields (mcp_service_name, openapi_json, server_url, etc.) are kept.

-- Step 1: Create new table for services
CREATE TABLE IF NOT EXISTS nexent.ag_outer_api_services (
    id BIGSERIAL PRIMARY KEY,
    mcp_service_name VARCHAR(100) NOT NULL,
    description TEXT,
    openapi_json JSONB,
    server_url VARCHAR(500),
    headers_template JSONB,
    tenant_id VARCHAR(100) NOT NULL,
    is_available BOOLEAN DEFAULT TRUE,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Step 2: Migrate data - one record per service
-- Use DISTINCT ON to get one record per (tenant_id, mcp_service_name)
-- Order by update_time DESC to keep the most recently updated record
INSERT INTO nexent.ag_outer_api_services (
    mcp_service_name,
    description,
    openapi_json,
    server_url,
    headers_template,
    tenant_id,
    is_available,
    create_time,
    update_time,
    created_by,
    updated_by,
    delete_flag
)
SELECT DISTINCT ON (t.tenant_id, t.mcp_service_name)
    t.mcp_service_name,
    t.description,
    t.openapi_json,
    t.server_url,
    t.headers_template,
    t.tenant_id,
    COALESCE(t.is_available, TRUE) as is_available,
    t.create_time,
    t.update_time,
    t.created_by,
    t.updated_by,
    t.delete_flag
FROM nexent.ag_outer_api_tools t
WHERE t.delete_flag != 'Y'
ORDER BY t.tenant_id, t.mcp_service_name, t.update_time DESC
ON CONFLICT DO NOTHING;

-- Step 3: Verify migration
SELECT 'Migrated services count: ' || COUNT(*) FROM nexent.ag_outer_api_services;

-- Step 4: Drop old table after successful migration
DROP TABLE IF EXISTS nexent.ag_outer_api_tools;

-- Step 5: Drop the old sequence (no longer needed)
DROP SEQUENCE IF EXISTS nexent.ag_outer_api_tools_id_seq;

-- nexent-migration-source: v2.0.2_0420_add_fk_to_ag_a2a_message_t.sql
-- nexent-migration-checksum: 1e90ca0f9ae7f6e3a6b0a14e09c80394742ed76f20a13081b51b205518495572
-- nexent-migration-probe: SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ag_a2a_message_t_task_id_fk' AND conrelid = 'nexent.ag_a2a_message_t'::regclass) OR EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'ag_a2a_external_agent_t' AND column_name = 'base_url');
-- =============================================================================
-- Add Foreign Key Constraint to ag_a2a_message_t
-- =============================================================================
-- Version: v2.0.2
-- Date: 2026-04-20
-- Description: Add foreign key constraint on task_id referencing ag_a2a_task_t(id)
-- Target Table: nexent.ag_a2a_message_t
-- =============================================================================

-- Add foreign key constraint: task_id references ag_a2a_task_t(id) with CASCADE delete
ALTER TABLE nexent.ag_a2a_message_t
    ADD CONSTRAINT ag_a2a_message_t_task_id_fk
    FOREIGN KEY (task_id)
    REFERENCES nexent.ag_a2a_task_t(id) ON DELETE CASCADE;

-- nexent-migration-source: v2.0.2_0425_add_is_a2a_to_ag_tenant_agent_version_t.sql
-- nexent-migration-checksum: 017977bb962a4612381fa0a0a1b14ae1c1a2a93d59a96f08f30ea667eee9b2c1
-- nexent-migration-probe: SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'ag_tenant_agent_version_t' AND column_name = 'is_a2a');
-- Add is_a2a column to ag_tenant_agent_version_t for tracking A2A Server agent publish status
-- This field indicates whether this version was published as an A2A Server agent

ALTER TABLE nexent.ag_tenant_agent_version_t
ADD COLUMN IF NOT EXISTS is_a2a BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.is_a2a IS 'Whether this version is published as an A2A Server agent';

-- nexent-migration-source: v2.0.3_0423_create_model_monitoring_record_t.sql
-- nexent-migration-checksum: 3a97d2b04452e63c9a6ea38ebe49705099ee53a8cc63a3c976da4bfcf77ed089
-- nexent-migration-probe: SELECT to_regclass('nexent.model_monitoring_record_t') IS NOT NULL;
-- Model Monitoring Record Table
-- Stores per-request LLM performance metrics for the monitoring feature.
-- Run this script against the 'nexent' schema in PostgreSQL.

CREATE TABLE IF NOT EXISTS nexent.model_monitoring_record_t (
    monitoring_id       SERIAL          PRIMARY KEY,
    model_id            INT4,
    model_name          VARCHAR(100)    NOT NULL,
    model_type          VARCHAR(20)     DEFAULT 'llm',
    agent_id            INT4,
    agent_name          VARCHAR(100),
    conversation_id     INT4,
    tenant_id           VARCHAR(100)    NOT NULL,
    user_id             VARCHAR(100),
    display_name        VARCHAR(100),
    request_duration_ms INT4,
    ttft_ms             INT4,
    input_tokens        INT4,
    output_tokens       INT4,
    total_tokens        INT4,
    generation_rate     FLOAT,
    is_streaming        BOOLEAN         DEFAULT FALSE,
    is_success          BOOLEAN         DEFAULT TRUE,
    is_error            BOOLEAN         DEFAULT FALSE,
    error_type          VARCHAR(50),
    error_message       TEXT,
    retry_count         INT4            DEFAULT 0,
    operation           VARCHAR(50),
    create_time         TIMESTAMP       DEFAULT NOW(),
    delete_flag         VARCHAR(1)      DEFAULT 'N'
);

-- Single-column indexes for common query patterns
CREATE INDEX IF NOT EXISTS ix_monitoring_model_id     ON nexent.model_monitoring_record_t (model_id);
CREATE INDEX IF NOT EXISTS ix_monitoring_tenant_id    ON nexent.model_monitoring_record_t (tenant_id);
CREATE INDEX IF NOT EXISTS ix_monitoring_agent_id     ON nexent.model_monitoring_record_t (agent_id);
CREATE INDEX IF NOT EXISTS ix_monitoring_create_time  ON nexent.model_monitoring_record_t (create_time);
CREATE INDEX IF NOT EXISTS ix_monitoring_is_error     ON nexent.model_monitoring_record_t (is_error);
CREATE INDEX IF NOT EXISTS ix_monitoring_model_type   ON nexent.model_monitoring_record_t (model_type);

-- Composite index for time-range queries per model
CREATE INDEX IF NOT EXISTS ix_monitoring_model_time   ON nexent.model_monitoring_record_t (model_id, create_time);

-- nexent-migration-source: v2.0.3_0430_add_user_oauth_account_t.sql
-- nexent-migration-checksum: bab30b3520bead4840bc989936d3b5a91d06ff8c8187c550b3627b415d855e97
-- nexent-migration-probe: SELECT to_regclass('nexent.user_oauth_account_t') IS NOT NULL;
-- Create user OAuth account table for third-party login (GitHub, WeChat, etc.)
CREATE TABLE IF NOT EXISTS nexent.user_oauth_account_t (
    oauth_account_id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    provider VARCHAR(30) NOT NULL,
    provider_user_id VARCHAR(200) NOT NULL,
    provider_email VARCHAR(255),
    provider_username VARCHAR(200),
    tenant_id VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag CHAR(1) DEFAULT 'N',
    CONSTRAINT uq_oauth_provider_user UNIQUE (provider, provider_user_id)
);

ALTER TABLE nexent.user_oauth_account_t OWNER TO "root";

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_user_oauth_account_t_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create a trigger to call the function before each update
CREATE TRIGGER update_user_oauth_account_t_update_time_trigger
BEFORE UPDATE ON nexent.user_oauth_account_t
FOR EACH ROW
EXECUTE FUNCTION update_user_oauth_account_t_update_time();

-- Add comments
COMMENT ON TABLE nexent.user_oauth_account_t IS 'User OAuth account table - third-party login bindings';
COMMENT ON COLUMN nexent.user_oauth_account_t.oauth_account_id IS 'OAuth account ID, primary key';
COMMENT ON COLUMN nexent.user_oauth_account_t.user_id IS 'Nexent user ID (Supabase UUID)';
COMMENT ON COLUMN nexent.user_oauth_account_t.provider IS 'OAuth provider name: github, wechat, gde, link_app';
COMMENT ON COLUMN nexent.user_oauth_account_t.provider_user_id IS 'User ID from the OAuth provider';
COMMENT ON COLUMN nexent.user_oauth_account_t.provider_email IS 'Email from the OAuth provider';
COMMENT ON COLUMN nexent.user_oauth_account_t.provider_username IS 'Display name from the OAuth provider';
COMMENT ON COLUMN nexent.user_oauth_account_t.tenant_id IS 'Tenant ID at time of linking';
COMMENT ON COLUMN nexent.user_oauth_account_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.user_oauth_account_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.user_oauth_account_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.user_oauth_account_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.user_oauth_account_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create index for user_id queries
CREATE INDEX IF NOT EXISTS idx_user_oauth_account_t_user_id
ON nexent.user_oauth_account_t (user_id);

-- nexent-migration-source: v2.0.4_0427_add_enable_context_manager_to_ag_tenant_agent_t.sql
-- nexent-migration-checksum: 5afe76cd3e57ee935e3fc0f32c9dc1e568162f5dce344ce1eaea3b1d7489a9ed
-- nexent-migration-probe: SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'ag_tenant_agent_t' AND column_name = 'enable_context_manager');
-- Migration: Add enable_context_manager column to ag_tenant_agent_t table
-- Date: 2025-04-27
-- Description: Add enable_context_manager field to control context management (compression) per agent

-- Add enable_context_manager column to ag_tenant_agent_t table
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS enable_context_manager BOOLEAN DEFAULT FALSE;

-- Add comment to the column
COMMENT ON COLUMN nexent.ag_tenant_agent_t.enable_context_manager IS 'Whether to enable context management (compression) for this agent';

-- nexent-migration-source: v2.0.4_0506_add_base_url_in_external_agent.sql
-- nexent-migration-checksum: 8e4059abf919ffd7637712a39c6826678fd6c19aeb3f648ed558707ffc3e567b
-- nexent-migration-probe: SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'ag_a2a_external_agent_t' AND column_name = 'base_url');
ALTER TABLE nexent.ag_a2a_external_agent_t
ADD COLUMN IF NOT EXISTS base_url VARCHAR(512);

COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.base_url IS 'Base URL for health checks (service root address)';

ALTER TABLE nexent.ag_a2a_message_t
    DROP CONSTRAINT IF EXISTS ag_a2a_message_t_task_id_fk;

ALTER TABLE nexent.ag_a2a_external_agent_relation_t
    DROP CONSTRAINT IF EXISTS fk_external_agent;

ALTER TABLE nexent.ag_a2a_artifact_t
    DROP CONSTRAINT IF EXISTS fk_artifact_task;

-- nexent-migration-source: v2.0.5_0511_add_auto_summary_fields_to_knowledge_record_t.sql
-- nexent-migration-checksum: e3507df5a3b37bb3b6b8b3bef1ecc1d3be1645679ad9ee4b4cc47bb297f35d60
-- nexent-migration-probe: SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'knowledge_record_t' AND column_name = 'summary_frequency') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'knowledge_record_t' AND column_name = 'last_summary_time') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'knowledge_record_t' AND column_name = 'last_doc_update_time');
-- Migration: Add auto-summary fields to knowledge_record_t table
-- Date: 2026-05-11
-- Description: Add summary_frequency, last_summary_time, and last_doc_update_time fields for auto-summary feature
-- This SQL consolidates fields added in multiple commits for clean upgrade path

-- Add summary_frequency column (auto-summary frequency configuration)
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS summary_frequency VARCHAR(10);

-- Add last_summary_time column (timestamp of last summary generation)
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS last_summary_time TIMESTAMP;

-- Add last_doc_update_time column (timestamp of last document add/delete operation)
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS last_doc_update_time TIMESTAMP;

-- Add comments to the columns
COMMENT ON COLUMN nexent.knowledge_record_t.summary_frequency IS 'Auto-summary frequency: 1h, 3h, 6h, 1d, 1w, or NULL (disabled)';
COMMENT ON COLUMN nexent.knowledge_record_t.last_summary_time IS 'Timestamp of last summary generation';
COMMENT ON COLUMN nexent.knowledge_record_t.last_doc_update_time IS 'Timestamp of last document add/delete operation, used for auto-summary optimization to skip unnecessary summary regeneration';

