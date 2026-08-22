-- Nexent merged SQL migrations: v2.2
-- This file is generated from historical migration files.

-- Rename params -> config_values, add config_schemas to ag_skill_info_t
-- Add tenant_id column for multi-tenancy support
ALTER TABLE nexent.ag_skill_info_t ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);

-- Add config_values and config_schemas to ag_skill_info_t
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name   = 'ag_skill_info_t'
          AND column_name  = 'params'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name   = 'ag_skill_info_t'
          AND column_name  = 'config_values'
    ) THEN
        ALTER TABLE nexent.ag_skill_info_t RENAME COLUMN params TO config_values;
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name   = 'ag_skill_info_t'
          AND column_name  = 'params'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name   = 'ag_skill_info_t'
          AND column_name  = 'config_values'
    ) THEN
        UPDATE nexent.ag_skill_info_t
        SET config_values = params
        WHERE config_values IS NULL
          AND params IS NOT NULL;
    END IF;
END $$;
ALTER TABLE nexent.ag_skill_info_t ADD COLUMN IF NOT EXISTS config_values JSON;
ALTER TABLE nexent.ag_skill_info_t ADD COLUMN IF NOT EXISTS config_schemas JSON;

-- Comments for ag_skill_info_t columns
COMMENT ON COLUMN nexent.ag_skill_info_t.tenant_id IS 'Tenant ID for multi-tenancy. NULL for pre-existing skills.';
COMMENT ON COLUMN nexent.ag_skill_info_t.config_values IS 'Runtime parameter values from config/config.yaml';
COMMENT ON COLUMN nexent.ag_skill_info_t.config_schemas IS 'Parameter metadata list from config/schema.yaml';

-- Add config_values and config_schemas to ag_skill_instance_t
ALTER TABLE nexent.ag_skill_instance_t ADD COLUMN IF NOT EXISTS config_values JSON;
ALTER TABLE nexent.ag_skill_instance_t ADD COLUMN IF NOT EXISTS config_schemas JSON;

-- Comments for ag_skill_instance_t columns
COMMENT ON COLUMN nexent.ag_skill_instance_t.config_values IS 'Per-agent runtime parameter values from config/config.yaml';
COMMENT ON COLUMN nexent.ag_skill_instance_t.config_schemas IS 'Per-agent parameter schema overrides from config/schema.yaml';

-- Add concurrency_limit column to model_record_t table
ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS concurrency_limit INTEGER DEFAULT NULL;

-- Add comment to the column
COMMENT ON COLUMN nexent.model_record_t.concurrency_limit IS 'Maximum concurrent requests for this model. Default is NULL (unlimited).';

-- Add timeout_seconds column to model_record_t table
ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER DEFAULT 120;

-- Add comment to the column
COMMENT ON COLUMN nexent.model_record_t.timeout_seconds IS 'Request timeout in seconds for this model. Default is 120 seconds.';

-- Migration: Add mcp_community_record_t table
-- Date: 2026-03-26
-- Description: Community MCP market table aligned with public-shareable fields from mcp_record_t.

SET search_path TO nexent;

BEGIN;

CREATE TABLE IF NOT EXISTS nexent.mcp_community_record_t (
    community_id SERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    mcp_name VARCHAR(100) NOT NULL,
    mcp_server VARCHAR(500) NOT NULL,
    source VARCHAR(30) DEFAULT 'community',
    version VARCHAR(50),
    registry_json JSONB,
    transport_type VARCHAR(30),
    config_json JSON,
    tags TEXT[],
    description TEXT,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.mcp_community_record_t OWNER TO root;

COMMENT ON TABLE nexent.mcp_community_record_t IS 'Community MCP market records, publishable from tenant MCP services';
COMMENT ON COLUMN nexent.mcp_community_record_t.community_id IS 'Community record ID, unique primary key';
COMMENT ON COLUMN nexent.mcp_community_record_t.tenant_id IS 'Publisher tenant ID';
COMMENT ON COLUMN nexent.mcp_community_record_t.user_id IS 'Publisher user ID';
COMMENT ON COLUMN nexent.mcp_community_record_t.mcp_name IS 'MCP name';
COMMENT ON COLUMN nexent.mcp_community_record_t.mcp_server IS 'MCP server URL';
COMMENT ON COLUMN nexent.mcp_community_record_t.source IS 'Source type, fixed to community for this table';
COMMENT ON COLUMN nexent.mcp_community_record_t.version IS 'MCP version';
COMMENT ON COLUMN nexent.mcp_community_record_t.registry_json IS 'Full MCP server metadata JSON for discovery and quick import';
COMMENT ON COLUMN nexent.mcp_community_record_t.transport_type IS 'Transport type: url/container';
COMMENT ON COLUMN nexent.mcp_community_record_t.config_json IS 'Public-shareable MCP configuration JSON';
COMMENT ON COLUMN nexent.mcp_community_record_t.tags IS 'Tags';
COMMENT ON COLUMN nexent.mcp_community_record_t.description IS 'Description';
COMMENT ON COLUMN nexent.mcp_community_record_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.mcp_community_record_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.mcp_community_record_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.mcp_community_record_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.mcp_community_record_t.delete_flag IS 'Soft delete flag: Y/N';

CREATE INDEX IF NOT EXISTS idx_mcp_community_tenant_delete
    ON nexent.mcp_community_record_t (tenant_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_community_name_delete
    ON nexent.mcp_community_record_t (mcp_name, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_community_transport_delete
    ON nexent.mcp_community_record_t (transport_type, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_community_user_delete
    ON nexent.mcp_community_record_t (user_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_community_tags_gin
    ON nexent.mcp_community_record_t USING GIN (tags);

CREATE OR REPLACE FUNCTION update_mcp_community_record_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_mcp_community_record_update_time() IS 'Auto-update update_time for mcp_community_record_t';

DROP TRIGGER IF EXISTS update_mcp_community_record_update_time_trigger ON nexent.mcp_community_record_t;
CREATE TRIGGER update_mcp_community_record_update_time_trigger
BEFORE UPDATE ON nexent.mcp_community_record_t
FOR EACH ROW
EXECUTE FUNCTION update_mcp_community_record_update_time();

COMMENT ON TRIGGER update_mcp_community_record_update_time_trigger ON nexent.mcp_community_record_t IS 'Trigger to maintain update_time';

COMMIT;

-- Migration: Extend mcp_record_t for MCP tools (direct schema)
-- Date: 2026-03-18
-- Description: One-step schema extension for mcp_record_t. No table merge, no data migration.

SET search_path TO nexent;

BEGIN;

-- 1) Extend mcp_record_t with final column names (idempotent)
ALTER TABLE IF EXISTS nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS source VARCHAR(30),
    ADD COLUMN IF NOT EXISTS registry_json JSONB,
    ADD COLUMN IF NOT EXISTS config_json JSON,
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS tags TEXT[],
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS container_port INTEGER;

-- 2) Add comments for new columns
COMMENT ON COLUMN nexent.mcp_record_t.source IS 'Source type: local/mcp_registry/community';
COMMENT ON COLUMN nexent.mcp_record_t.registry_json IS 'Full MCP registry server.json snapshot';
COMMENT ON COLUMN nexent.mcp_record_t.config_json IS 'MCP config data';
COMMENT ON COLUMN nexent.mcp_record_t.enabled IS 'Enabled';
COMMENT ON COLUMN nexent.mcp_record_t.tags IS 'Tags';
COMMENT ON COLUMN nexent.mcp_record_t.description IS 'Description';
COMMENT ON COLUMN nexent.mcp_record_t.container_port IS 'Host port bound for containerized MCP service';

-- 3) Add indexes for common management queries
CREATE INDEX IF NOT EXISTS idx_mcp_record_t_tenant_delete
    ON nexent.mcp_record_t (tenant_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_record_t_tenant_name
    ON nexent.mcp_record_t (tenant_id, mcp_name, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_record_t_tenant_server
    ON nexent.mcp_record_t (tenant_id, mcp_server, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_record_t_tags_gin
    ON nexent.mcp_record_t USING GIN (tags);

COMMIT;

CREATE TABLE IF NOT EXISTS nexent.user_cas_session_t (
    cas_session_id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,
    cas_user_id VARCHAR(200) NOT NULL,
    cas_session_index VARCHAR(500),
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS ix_user_cas_session_session_id
    ON nexent.user_cas_session_t (session_id);
CREATE INDEX IF NOT EXISTS ix_user_cas_session_user_id
    ON nexent.user_cas_session_t (user_id);
CREATE INDEX IF NOT EXISTS ix_user_cas_session_cas_user_id
    ON nexent.user_cas_session_t (cas_user_id);

COMMENT ON TABLE nexent.user_cas_session_t IS 'Server-side session records for CAS SSO login and logout synchronization';
COMMENT ON COLUMN nexent.user_cas_session_t.session_id IS 'JWT sid claim for revocation checks';
COMMENT ON COLUMN nexent.user_cas_session_t.cas_user_id IS 'User identifier returned by CAS';
COMMENT ON COLUMN nexent.user_cas_session_t.cas_session_index IS 'CAS SessionIndex or service ticket';

-- Migration: Add custom_headers column to mcp_record_t
-- Date: 2026-05-26
-- Description: Add custom_headers field to store custom HTTP headers for MCP server requests

SET search_path TO nexent;

BEGIN;

-- Add custom_headers column if it doesn't exist
ALTER TABLE nexent.mcp_record_t
ADD COLUMN IF NOT EXISTS custom_headers JSON DEFAULT NULL;

-- Add comment to the column
COMMENT ON COLUMN nexent.mcp_record_t.custom_headers IS 'Custom HTTP headers as JSON object for MCP server requests';

COMMIT;

-- Migration: ASSET_OWNER role permissions and invitation type comment
-- Date: 2026-05-29
-- Description: Add ASSET_OWNER role permissions, SU asset-owner invite permissions,
--              update invitation code_type comment, and ensure ag_skill_info_t.tenant_id exists
-- Source: commit 15cece97692db2372a978cbdf21b5d5316e79f30 (init.sql)

SET search_path TO nexent;

BEGIN;

COMMENT ON COLUMN nexent.tenant_invitation_code_t.code_type IS
    'Invitation code type: ADMIN_INVITE, DEV_INVITE, USER_INVITE, ASSET_OWNER_INVITE';

INSERT INTO nexent.role_permission_t
    (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES
    (188, 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'CREATE'),
    (189, 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'READ'),
    (190, 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'UPDATE'),
    (191, 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'DELETE'),
    (192, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
    (193, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents'),
    (194, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
    (195, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
    (196, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
    (197, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/market'),
    (198, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
    (199, 'ASSET_OWNER', 'RESOURCE', 'AGENT', 'CREATE'),
    (200, 'ASSET_OWNER', 'RESOURCE', 'AGENT', 'READ'),
    (201, 'ASSET_OWNER', 'RESOURCE', 'AGENT', 'UPDATE'),
    (202, 'ASSET_OWNER', 'RESOURCE', 'AGENT', 'DELETE'),
    (203, 'ASSET_OWNER', 'RESOURCE', 'SKILL', 'CREATE'),
    (204, 'ASSET_OWNER', 'RESOURCE', 'SKILL', 'READ'),
    (205, 'ASSET_OWNER', 'RESOURCE', 'SKILL', 'UPDATE'),
    (206, 'ASSET_OWNER', 'RESOURCE', 'SKILL', 'DELETE'),
    (207, 'ASSET_OWNER', 'RESOURCE', 'KB', 'CREATE'),
    (208, 'ASSET_OWNER', 'RESOURCE', 'KB', 'READ'),
    (209, 'ASSET_OWNER', 'RESOURCE', 'KB', 'UPDATE'),
    (210, 'ASSET_OWNER', 'RESOURCE', 'KB', 'DELETE'),
    (211, 'ASSET_OWNER', 'RESOURCE', 'MCP', 'CREATE'),
    (212, 'ASSET_OWNER', 'RESOURCE', 'MCP', 'READ'),
    (213, 'ASSET_OWNER', 'RESOURCE', 'MCP', 'UPDATE'),
    (214, 'ASSET_OWNER', 'RESOURCE', 'MCP', 'DELETE'),
    (215, 'ASSET_OWNER', 'RESOURCE', 'MODEL', 'CREATE'),
    (216, 'ASSET_OWNER', 'RESOURCE', 'MODEL', 'READ'),
    (217, 'ASSET_OWNER', 'RESOURCE', 'MODEL', 'UPDATE'),
    (218, 'ASSET_OWNER', 'RESOURCE', 'MODEL', 'DELETE'),
    (219, 'ASSET_OWNER', 'RESOURCE', 'USER.ROLE', 'READ'),
    (220, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
    (221, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/asset-owner-resources')
ON CONFLICT (role_permission_id) DO NOTHING;

COMMIT;

-- Migration: Add layered ReAct self-verification config to agents
-- Description: Stores per-agent verification controls for step-level and final-answer validation.

ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS verification_config JSONB;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.verification_config IS 'Layered ReAct self-verification configuration';

-- Migration: Add preserve_source_file to knowledge_record_t table
-- Date: 2026-06-01
-- Description: Whether to preserve uploaded source documents after vectorization (default: true)

ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS preserve_source_file BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN nexent.knowledge_record_t.preserve_source_file IS 'Whether to preserve uploaded source documents after vectorization';

-- Migration: Add greeting_message and example_questions columns to ag_tenant_agent_t table
-- Date: 2026-06-03
-- Description: Add greeting message and example questions fields for agent chat initial screen

-- Add greeting_message column to ag_tenant_agent_t table
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS greeting_message TEXT;

-- Add example_questions column to ag_tenant_agent_t table
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS example_questions JSONB;

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_tenant_agent_t.greeting_message IS 'Agent greeting message displayed on chat initial screen';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.example_questions IS 'List of example questions for starting a conversation with this agent';

-- Migration: Add ag_agent_repository_t table
-- Date: 2026-06-05
-- Description: Agent marketplace repository for frozen shareable agent snapshots.

SET search_path TO nexent;

BEGIN;

CREATE SEQUENCE IF NOT EXISTS nexent.ag_agent_repository_t_agent_repository_id_seq;

CREATE TABLE IF NOT EXISTS nexent.ag_agent_repository_t (
    agent_repository_id BIGINT NOT NULL DEFAULT nextval('nexent.ag_agent_repository_t_agent_repository_id_seq'),
    publisher_tenant_id VARCHAR(100) NOT NULL,
    publisher_user_id VARCHAR(100) NOT NULL,
    agent_id INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(100),
    description TEXT,
    author VARCHAR(100),
    submitted_by VARCHAR(100),
    tags TEXT[],
    tool_count INTEGER,
    icon VARCHAR(100),
    downloads INTEGER DEFAULT 0,
    version_name VARCHAR(100),
    agent_info_json JSONB NOT NULL,
    status VARCHAR(30) DEFAULT 'not_shared',
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT ag_agent_repository_t_pkey PRIMARY KEY (agent_repository_id)
);

ALTER SEQUENCE nexent.ag_agent_repository_t_agent_repository_id_seq
    OWNED BY nexent.ag_agent_repository_t.agent_repository_id;

ALTER TABLE nexent.ag_agent_repository_t OWNER TO root;

-- Upgrade legacy ag_agent_repository_t schema if table already exists
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'nexent' AND table_name = 'ag_agent_repository_t'
      AND column_name = 'source_version_no'
  ) THEN
    ALTER TABLE nexent.ag_agent_repository_t
      RENAME COLUMN source_version_no TO version_no;
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'nexent' AND table_name = 'ag_agent_repository_t'
      AND column_name = 'version_label'
  ) THEN
    ALTER TABLE nexent.ag_agent_repository_t
      RENAME COLUMN version_label TO version_name;
  END IF;
END $$;

ALTER TABLE nexent.ag_agent_repository_t
  ADD COLUMN IF NOT EXISTS submitted_by VARCHAR(100),
  ADD COLUMN IF NOT EXISTS icon VARCHAR(100),
  ADD COLUMN IF NOT EXISTS downloads INTEGER DEFAULT 0;

DROP INDEX IF EXISTS nexent.uq_agent_repository_tenant_agent_active;

COMMENT ON TABLE nexent.ag_agent_repository_t IS 'Agent marketplace repository for frozen shareable agent snapshots';
COMMENT ON COLUMN nexent.ag_agent_repository_t.agent_repository_id IS 'Agent repository listing ID, unique primary key';
COMMENT ON COLUMN nexent.ag_agent_repository_t.publisher_tenant_id IS 'Publisher tenant ID';
COMMENT ON COLUMN nexent.ag_agent_repository_t.publisher_user_id IS 'Publisher user ID';
COMMENT ON COLUMN nexent.ag_agent_repository_t.agent_id IS 'Root agent ID from ag_tenant_agent_t; unique per version_no when active (delete_flag = N)';
COMMENT ON COLUMN nexent.ag_agent_repository_t.version_no IS 'Published version number frozen at share time';
COMMENT ON COLUMN nexent.ag_agent_repository_t.name IS 'Root agent programmatic name for display and search';
COMMENT ON COLUMN nexent.ag_agent_repository_t.display_name IS 'Root agent display name';
COMMENT ON COLUMN nexent.ag_agent_repository_t.description IS 'Root agent description';
COMMENT ON COLUMN nexent.ag_agent_repository_t.author IS 'Agent author';
COMMENT ON COLUMN nexent.ag_agent_repository_t.submitted_by IS 'Submitter email when listing enters pending_review';
COMMENT ON COLUMN nexent.ag_agent_repository_t.tags IS 'Marketplace tags';
COMMENT ON COLUMN nexent.ag_agent_repository_t.tool_count IS 'Total tool count across all agents in the bundle (display only)';
COMMENT ON COLUMN nexent.ag_agent_repository_t.version_name IS 'Repository entry version name for display (from ag_tenant_agent_version_t)';
COMMENT ON COLUMN nexent.ag_agent_repository_t.icon IS 'Marketplace card icon (emoji or URL)';
COMMENT ON COLUMN nexent.ag_agent_repository_t.downloads IS 'Marketplace download/copy count for card display';
COMMENT ON COLUMN nexent.ag_agent_repository_t.agent_info_json IS 'Frozen ExportAndImportDataFormat snapshot with optional skills';
COMMENT ON COLUMN nexent.ag_agent_repository_t.status IS 'Listing status: not_shared (未共享) / pending_review (待审核) / rejected (审核驳回) / shared (已共享)';
COMMENT ON COLUMN nexent.ag_agent_repository_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_agent_repository_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_agent_repository_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.ag_agent_repository_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.ag_agent_repository_t.delete_flag IS 'Soft delete flag: Y/N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_repository_agent_version_active
    ON nexent.ag_agent_repository_t (agent_id, version_no)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_agent_repository_publisher_delete
    ON nexent.ag_agent_repository_t (publisher_tenant_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_agent_repository_status_delete
    ON nexent.ag_agent_repository_t (status, delete_flag);

CREATE INDEX IF NOT EXISTS idx_agent_repository_name_delete
    ON nexent.ag_agent_repository_t (name, delete_flag);

CREATE INDEX IF NOT EXISTS idx_agent_repository_tags_gin
    ON nexent.ag_agent_repository_t USING GIN (tags);

CREATE OR REPLACE FUNCTION update_ag_agent_repository_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_ag_agent_repository_update_time() IS 'Auto-update update_time for ag_agent_repository_t';

DROP TRIGGER IF EXISTS update_ag_agent_repository_update_time_trigger ON nexent.ag_agent_repository_t;
CREATE TRIGGER update_ag_agent_repository_update_time_trigger
BEFORE UPDATE ON nexent.ag_agent_repository_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_agent_repository_update_time();

COMMENT ON TRIGGER update_ag_agent_repository_update_time_trigger ON nexent.ag_agent_repository_t IS 'Trigger to maintain update_time';

COMMIT;

-- Migration: Add selected_agent_version_no to ag_agent_relation_t
-- Date: 2026-06-09
-- Description: Pin child agent version on parent-child relations at publish time.

SET search_path TO nexent;

BEGIN;

ALTER TABLE nexent.ag_agent_relation_t
    ADD COLUMN IF NOT EXISTS selected_agent_version_no INTEGER;

COMMENT ON COLUMN nexent.ag_agent_relation_t.selected_agent_version_no IS
    'Pinned version of selected_agent_id. NULL = use child current published version at runtime (legacy/draft).';

COMMIT;

-- Source migration: v2.2.0_0615_context_management_capacity_schema.sql

-- Migration kind: REQUIRED_SCHEMA
-- Required for: all upgraded deployments before running W1/W2 context-management code.
-- Reason: new code reads/writes these model capacity, monitoring snapshot, and agent override columns.

-- ============================================================
-- W1: Add explicit model token-capacity fields to model_record_t
-- ============================================================
-- All columns are nullable and additive; legacy max_tokens stays as a deprecated
-- output-cap alias until consumers migrate.

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS context_window_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS max_input_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS max_output_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS default_output_reserve_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS tokenizer_family VARCHAR(100) DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS capacity_source VARCHAR(100) DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS capability_profile_version VARCHAR(100) DEFAULT NULL;

COMMENT ON COLUMN nexent.model_record_t.context_window_tokens IS 'Total combined input/output context window in tokens, when the provider uses a combined window. Nullable.';
COMMENT ON COLUMN nexent.model_record_t.max_input_tokens IS 'Provider hard input-token limit when distinct from the combined window. Nullable.';
COMMENT ON COLUMN nexent.model_record_t.max_output_tokens IS 'Provider-supported or operator-configured completion-output cap. Replaces the ambiguous LLM meaning of max_tokens. Nullable.';
COMMENT ON COLUMN nexent.model_record_t.default_output_reserve_tokens IS 'Default output allowance reserved per request before constructing input context. Nullable.';
COMMENT ON COLUMN nexent.model_record_t.tokenizer_family IS 'Token-counting strategy or provider/model tokenizer identifier mapped via tokenizer_registry. Nullable.';
COMMENT ON COLUMN nexent.model_record_t.capacity_source IS 'Source of the persisted capacity value. Optional values: operator, profile, provider_candidate, legacy, unknown.';
COMMENT ON COLUMN nexent.model_record_t.capability_profile_version IS 'Version of the approved provider/model capability profile used by the request, e.g. openai/gpt-4o@1.';

-- ============================================================
-- W1: Persist resolved model capacity snapshot fields on monitoring records
-- ============================================================

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS context_window_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS default_output_reserve_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS capability_profile_version VARCHAR(100) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS capacity_source VARCHAR(100) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS requested_output_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS provider_input_limit_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS tokenizer_family VARCHAR(100) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS counting_mode VARCHAR(20) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS unknown_capabilities JSONB DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS capacity_fingerprint VARCHAR(64) DEFAULT NULL;

COMMENT ON COLUMN nexent.model_monitoring_record_t.context_window_tokens IS 'Resolved total combined model context window for this request';
COMMENT ON COLUMN nexent.model_monitoring_record_t.default_output_reserve_tokens IS 'Default output allowance reserved before input context construction';
COMMENT ON COLUMN nexent.model_monitoring_record_t.capability_profile_version IS 'Version of the resolved capacity profile for this request';
COMMENT ON COLUMN nexent.model_monitoring_record_t.capacity_source IS 'Dominant source of resolved capacity fields for this request';
COMMENT ON COLUMN nexent.model_monitoring_record_t.requested_output_tokens IS 'Output tokens requested or reserved during capacity resolution';
COMMENT ON COLUMN nexent.model_monitoring_record_t.provider_input_limit_tokens IS 'Resolved provider input-token limit used by context management';
COMMENT ON COLUMN nexent.model_monitoring_record_t.tokenizer_family IS 'Tokenizer family used for request token counting';
COMMENT ON COLUMN nexent.model_monitoring_record_t.counting_mode IS 'Token counting mode for the request: exact or estimated';
COMMENT ON COLUMN nexent.model_monitoring_record_t.unknown_capabilities IS 'Structured list of capacity capabilities unknown at resolution time';
COMMENT ON COLUMN nexent.model_monitoring_record_t.capacity_fingerprint IS 'Fingerprint of the resolved model capacity snapshot';

-- ============================================================
-- W2: Add per-agent requested_output_tokens override
-- ============================================================

ALTER TABLE nexent.ag_tenant_agent_t
  ADD COLUMN IF NOT EXISTS requested_output_tokens INTEGER NULL;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.requested_output_tokens IS
  'Per-agent override for W2 requested_output_tokens. NULL means inherit '
  'the resolved model-level default. Must satisfy 0 < value <= '
  'max_output_tokens from the resolved W1 capacity at save time.';

-- ============================================================
-- W2: Add safe input budget snapshot fields to model monitoring records
-- ============================================================

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_fingerprint VARCHAR(64) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_w1_fingerprint VARCHAR(64) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_requested_output_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_output_reserve_source VARCHAR(32) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_provider_input_limit_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_uncertainty_reserve_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_uncertainty_reserve_basis VARCHAR(64) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_soft_limit_ratio FLOAT DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_soft_input_budget_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_hard_input_budget_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_warnings JSONB DEFAULT NULL;

COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_fingerprint IS 'Fingerprint of the resolved W2 safe input budget snapshot';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_w1_fingerprint IS 'W1 capacity fingerprint consumed by the W2 budget snapshot';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_requested_output_tokens IS 'W2 trusted requested output tokens used at dispatch';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_output_reserve_source IS 'Source of the W2 requested output token reserve';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_provider_input_limit_tokens IS 'Provider input limit after applying the W2 output reserve';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_uncertainty_reserve_tokens IS 'Additional W2 uncertainty reserve deducted from input budget';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_uncertainty_reserve_basis IS 'Basis used for the W2 uncertainty reserve';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_soft_limit_ratio IS 'W2 soft input budget ratio';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_soft_input_budget_tokens IS 'W2 soft input budget where proactive compression begins';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_hard_input_budget_tokens IS 'W2 hard input budget consumed by W3 final fit';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_warnings IS 'Structured W2 budget warnings active for this request';

-- Source migration: v2.2.1_0618_add_conversation_share_tables.sql

CREATE TABLE IF NOT EXISTS nexent.conversation_share_t (
    share_id integer NOT NULL PRIMARY KEY,
    share_token varchar(64) NOT NULL UNIQUE,
    conversation_id integer NOT NULL,
    tenant_id varchar(100),
    title varchar(200),
    mode varchar(30) DEFAULT 'selected',
    selected_message_ids jsonb,
    snapshot_json jsonb NOT NULL,
    status varchar(30) DEFAULT 'active',
    expire_time timestamp without time zone,
    create_time timestamp without time zone DEFAULT now(),
    update_time timestamp without time zone DEFAULT now(),
    created_by varchar(100),
    updated_by varchar(100),
    delete_flag varchar(1) DEFAULT 'N'
);

CREATE SEQUENCE IF NOT EXISTS nexent.conversation_share_t_share_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE nexent.conversation_share_t_share_id_seq OWNED BY nexent.conversation_share_t.share_id;
ALTER TABLE ONLY nexent.conversation_share_t ALTER COLUMN share_id SET DEFAULT nextval('nexent.conversation_share_t_share_id_seq'::regclass);

CREATE INDEX IF NOT EXISTS idx_conversation_share_token ON nexent.conversation_share_t (share_token);
CREATE INDEX IF NOT EXISTS idx_conversation_share_conversation_id ON nexent.conversation_share_t (conversation_id);

CREATE TABLE IF NOT EXISTS nexent.conversation_share_asset_t (
    share_asset_id integer NOT NULL PRIMARY KEY,
    asset_id varchar(64) NOT NULL UNIQUE,
    share_token varchar(64) NOT NULL,
    object_name varchar(1000) NOT NULL,
    filename varchar(500),
    content_type varchar(200),
    size bigint,
    source_kind varchar(50),
    metadata_json jsonb,
    create_time timestamp without time zone DEFAULT now(),
    update_time timestamp without time zone DEFAULT now(),
    created_by varchar(100),
    updated_by varchar(100),
    delete_flag varchar(1) DEFAULT 'N'
);

CREATE SEQUENCE IF NOT EXISTS nexent.conversation_share_asset_t_share_asset_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE nexent.conversation_share_asset_t_share_asset_id_seq OWNED BY nexent.conversation_share_asset_t.share_asset_id;
ALTER TABLE ONLY nexent.conversation_share_asset_t ALTER COLUMN share_asset_id SET DEFAULT nextval('nexent.conversation_share_asset_t_share_asset_id_seq'::regclass);

CREATE INDEX IF NOT EXISTS idx_conversation_share_asset_token ON nexent.conversation_share_asset_t (share_token);
CREATE INDEX IF NOT EXISTS idx_conversation_share_asset_id ON nexent.conversation_share_asset_t (asset_id);

-- Source migration: v2.2.2_0622_update_left_nav_menu.sql

-- ============================================================
-- Menu Structure Migration V2
-- Migration Date: 2026-06-22
-- ============================================================

-- Step 1: Clear all existing LEFT_NAV_MENU permissions
BEGIN;

DELETE FROM nexent.role_permission_t
WHERE permission_category = 'VISIBILITY' AND permission_type = 'LEFT_NAV_MENU';

ALTER TABLE nexent.role_permission_t
ADD COLUMN IF NOT EXISTS parent_key VARCHAR(50);
-- ============================================================
-- New Menu Structure:
-- ROOT:  /, /chat, /agent-dev, /resource-space, /resource-manage, /owner-manage, /users
-- AGENT-DEV: /models, /knowledges, /agents, /memory
-- RESOURCE-SPACE: /agent-space, /mcp-space, /skill-space
-- ============================================================
-- ID Format: <role_prefix>xx
--   SU=10xx, ADMIN=11xx, DEV=12xx, USER=13xx, SPEED=14xx, ASSET_OWNER=15xx
-- parent_key: NULL for first-level, parent route for second-level
-- ============================================================

-- SU Menus (root level)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1001, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1002, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-manage'),
(1003, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/owner-manage');

-- ADMIN Menus (root level)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1101, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1102, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(1103, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-dev'),
(1104, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-space'),
(1105, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-manage'),
(1106, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/users');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1107, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/models', '/agent-dev'),
(1108, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges', '/agent-dev'),
(1109, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents', '/agent-dev'),
(1110, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory', '/agent-dev');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1111, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-space', '/resource-space'),
(1112, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-space', '/resource-space'),
(1113, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/skill-space', '/resource-space');

-- DEV Menus (NO /resource-manage, root level)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1201, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1202, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(1203, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-dev'),
(1204, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-space'),
(1205, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/users');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1206, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/models', '/agent-dev'),
(1207, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges', '/agent-dev'),
(1208, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents', '/agent-dev'),
(1209, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory', '/agent-dev');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1210, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-space', '/resource-space'),
(1211, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-space', '/resource-space'),
(1212, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/skill-space', '/resource-space');

-- USER Menus (Minimal, all root level)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1301, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1302, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(1303, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(1304, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/users');

-- SPEED Menus (root level)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1401, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1402, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(1403, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-dev'),
(1404, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-space'),
(1405, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-manage');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1406, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/models', '/agent-dev'),
(1407, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges', '/agent-dev'),
(1408, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents', '/agent-dev'),
(1409, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory', '/agent-dev');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1410, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-space', '/resource-space'),
(1411, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-space', '/resource-space'),
(1412, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/skill-space', '/resource-space');

-- ASSET_OWNER Menus (root level; /owner-manage is SU-only, see v2.3.0_0713_move_owner_manage_to_su.sql)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1501, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(1502, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(1503, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-dev'),
(1504, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-space');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1506, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/models', '/agent-dev'),
(1507, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges', '/agent-dev'),
(1508, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents', '/agent-dev');
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key) VALUES
(1509, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-space', '/resource-space'),
(1510, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-space', '/resource-space'),
(1511, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/skill-space', '/resource-space');

COMMIT;

-- Source migration: v2.2.2_0624_migrate_agent_model_id_to_list.sql

-- Migration: Change ag_tenant_agent_t.model_id to model_ids (list of integers)
-- Date: 2026-06-17
-- Description: Migrate agent model configuration from single model_id to model_ids list
--
-- Idempotency notes:
-- This migration is executed on every container restart together with all other
-- incremental migrations. The follow-up migration
--   v2.2.2_0626_drop_agent_model_id_and_model_name.sql
-- removes ag_tenant_agent_t.model_id (and model_name). Therefore, on a re-run
-- the model_id column may already be absent. Every step that references
-- model_id must be guarded so the script remains a no-op in that state.
--
-- Migration strategy:
-- 1. Add new model_ids column as ARRAY(Integer) if it doesn't already exist
--    (idempotent via ADD COLUMN IF NOT EXISTS).
-- 2. If model_id still exists, backfill model_ids from model_id only when
--    model_ids is NULL or an empty array. Existing non-empty values are
--    preserved so the migration does not clobber data written by newer code.
-- 3. Set column comments (guarded so missing columns do not error).

SET search_path TO nexent;

BEGIN;

-- 1) Add model_ids column if it doesn't exist.
-- ADD COLUMN IF NOT EXISTS is a no-op when the column already exists, so
-- this statement is safe to re-run on every startup.
ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS model_ids INTEGER[] DEFAULT NULL;

-- 2) Backfill model_ids from the legacy single-value model_id column.
-- Only runs when model_id still exists. When model_id has already been
-- dropped by a later migration (e.g. v2.2.2_0626_drop_agent_model_id_and_model_name.sql),
-- this step is skipped and the script remains a safe no-op.
-- "Empty" is defined as either NULL or an empty array ('{}'); both
-- COALESCE(array_length(model_ids, 1), 0) = 0 and model_ids IS NULL match
-- these cases. Rows whose model_ids already has values are left untouched.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name = 'ag_tenant_agent_t'
          AND column_name = 'model_id'
    ) THEN
        UPDATE nexent.ag_tenant_agent_t
        SET model_ids = ARRAY[model_id]
        WHERE model_id IS NOT NULL
          AND (model_ids IS NULL OR COALESCE(array_length(model_ids, 1), 0) = 0);
    END IF;
END $$;

-- 3) Update column comments.
-- model_ids is created above (or was created on an earlier run) so the
-- comment can be applied unconditionally. COMMENT ON COLUMN raises an
-- error if the column is missing, so we still guard it for safety.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name = 'ag_tenant_agent_t'
          AND column_name = 'model_ids'
    ) THEN
        COMMENT ON COLUMN nexent.ag_tenant_agent_t.model_ids IS
            'List of model IDs, foreign key references to model_record_t.model_id, max 5 models';
    END IF;
END $$;

-- 4) Add a deprecation comment to model_id, only when the column still exists.
-- Once v2.2.2_0626_drop_agent_model_id_and_model_name.sql has dropped it,
-- this block is skipped.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name = 'ag_tenant_agent_t'
          AND column_name = 'model_id'
    ) THEN
        COMMENT ON COLUMN nexent.ag_tenant_agent_t.model_id IS
            '[DEPRECATED] Single model ID, use model_ids instead';
    END IF;
END $$;

COMMIT;

-- Source migration: v2.2.2_0627_backfill_from_catalog.sql

-- Catalog revision: 2026-06-27.1
-- Catalog entries: 66
--
-- Migration kind: RECOMMENDED_DATA_FIX
-- Idempotent: COALESCE + IS NULL guards protect existing values.
-- Safe: enforces max_output < context_window via GREATEST/LEAST.
--
-- Phases:
--   1a  Bare LLM/VLM rows that match a catalog entry by
--       (model_factory, model_repo, model_name) -> fill capacity
--       fields + tag capacity_source='profile' + profile_version.
--   1b  Already-filled rows that match a catalog entry AND whose
--       context_window_tokens and max_output_tokens exactly equal
--       the catalog values -> tag profile_version only. capacity_
--       source stays whatever it was (typically 'operator'); we
--       don't rewrite provenance, we just add the dispatch tag so
--       dispatch_profile_hit_total can fire.
--    2  Remaining bare LLM/VLM rows -> safe defaults.
--    3  Clamp default_output_reserve_tokens to <= max_output_tokens.
--
-- Pre-run self-check (rows whose capability_profile_version is NULL):
--
--   SELECT model_id, model_repo, model_name, model_factory,
--          context_window_tokens, max_output_tokens, capability_profile_version
--     FROM nexent.model_record_t
--    WHERE delete_flag = 'N'
--      AND COALESCE(model_type, 'llm') IN ('llm', 'vlm')
--      AND capability_profile_version IS NULL;

-- ============================================================
-- Phase 1a: Backfill bare rows that match approved catalog entries
-- ============================================================

DO $$
DECLARE
    v_updated INTEGER := 0;
    v_total   INTEGER := 0;
    c_active_flag     CONSTANT TEXT := 'N';
    c_source_profile  CONSTANT TEXT := 'profile';
BEGIN
    -- dashscope (4 entries)
    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(131072, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 131072) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'dashscope/qwen-plus@1')
     WHERE LOWER(model_factory) = 'dashscope'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'qwen-plus'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(1000000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 1000000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'dashscope/qwen-turbo@1')
     WHERE LOWER(model_factory) = 'dashscope'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'qwen-turbo'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(1000000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(65536, COALESCE(context_window_tokens, 1000000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 65536))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'dashscope/qwen3.7-max@1')
     WHERE LOWER(model_factory) = 'dashscope'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'qwen3.7-max'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(200000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(131072, COALESCE(context_window_tokens, 200000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 131072))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'dashscope/glm-5.1@1')
     WHERE LOWER(model_factory) = 'dashscope'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'glm-5.1'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    -- deepseek (4 entries)
    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(1000000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(384000, COALESCE(context_window_tokens, 1000000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 384000))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'deepseek/deepseek-chat@2')
     WHERE LOWER(model_factory) = 'deepseek'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'deepseek-chat'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(1000000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(384000, COALESCE(context_window_tokens, 1000000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 384000))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'deepseek/deepseek-reasoner@2')
     WHERE LOWER(model_factory) = 'deepseek'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'deepseek-reasoner'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(1000000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(384000, COALESCE(context_window_tokens, 1000000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 384000))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'deepseek/deepseek-v4-flash@1')
     WHERE LOWER(model_factory) = 'deepseek'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'deepseek-v4-flash'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(1000000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(384000, COALESCE(context_window_tokens, 1000000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 384000))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'deepseek/deepseek-v4-pro@1')
     WHERE LOWER(model_factory) = 'deepseek'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'deepseek-v4-pro'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    -- openai (2 entries)
    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(128000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 128000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'openai/gpt-4o@1')
     WHERE LOWER(model_factory) = 'openai'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'gpt-4o'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(1000000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(32768, COALESCE(context_window_tokens, 1000000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 32768))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'openai/gpt-4.1@1')
     WHERE LOWER(model_factory) = 'openai'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'gpt-4.1'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    -- silicon (56 entries)
    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(65536, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 65536))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3.6-27b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.6-27B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(131072, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 131072))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/kimi-k2.6@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/moonshotai'
       AND model_name = 'Kimi-K2.6'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(1048576, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(384000, COALESCE(context_window_tokens, 1048576) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 384000))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/deepseek-v4-pro-sf@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-V4-Pro'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(1048576, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(384000, COALESCE(context_window_tokens, 1048576) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 384000))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/deepseek-v4-flash-sf@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-V4-Flash'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(164000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 164000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/deepseek-v3.2@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-V3.2'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(164000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 164000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/deepseek-v3.1-terminus@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-V3.1-Terminus'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(163840, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 163840) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/deepseek-r1@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-R1'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(164000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 164000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/deepseek-v3@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-V3'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(131072, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 131072) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/deepseek-r1-0528-qwen3-8b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-R1-0528-Qwen3-8B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(164000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 164000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/deepseek-v3.2-pro@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/deepseek-ai'
       AND model_name = 'DeepSeek-V3.2'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(164000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 164000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/deepseek-v3.1-terminus-pro@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/deepseek-ai'
       AND model_name = 'DeepSeek-V3.1-Terminus'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(163840, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 163840) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/deepseek-r1-pro@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/deepseek-ai'
       AND model_name = 'DeepSeek-R1'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(164000, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 164000) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/deepseek-v3-pro@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/deepseek-ai'
       AND model_name = 'DeepSeek-V3'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3.6-35b-a3b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.6-35B-A3B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3.5-397b-a17b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-397B-A17B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3.5-122b-a10b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-122B-A10B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3.5-35b-a3b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-35B-A3B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3.5-27b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-27B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3.5-9b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-9B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3.5-4b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-4B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-vl-32b-instruct@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-32B-Instruct'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(32768, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 32768))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-vl-32b-thinking@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-32B-Thinking'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-vl-8b-instruct@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-8B-Instruct'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(32768, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 32768))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-vl-8b-thinking@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-8B-Thinking'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-vl-30b-a3b-instruct@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-30B-A3B-Instruct'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(32768, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 32768))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-vl-30b-a3b-thinking@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-30B-A3B-Thinking'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-omni-30b-a3b-instruct@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-Omni-30B-A3B-Instruct'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-omni-30b-a3b-thinking@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-Omni-30B-A3B-Thinking'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-omni-30b-a3b-captioner@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-Omni-30B-A3B-Captioner'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(65536, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 65536))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-coder-30b-a3b-instruct@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-Coder-30B-A3B-Instruct'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-30b-a3b-instruct-2507@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-30B-A3B-Instruct-2507'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(131072, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 131072) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-32b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-32B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(131072, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 131072) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-14b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-14B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(131072, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 131072) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen3-8b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-8B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(131072, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 131072) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen2.5-72b-instruct-128k@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen2.5-72B-Instruct-128K'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen2.5-72b-instruct@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen2.5-72B-Instruct'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen2.5-32b-instruct@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen2.5-32B-Instruct'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen2.5-14b-instruct@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen2.5-14B-Instruct'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/qwen2.5-7b-instruct@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen2.5-7B-Instruct'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/glm-4-32b-0414@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'THUDM'
       AND model_name = 'GLM-4-32B-0414'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/glm-z1-9b-0414@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'THUDM'
       AND model_name = 'GLM-Z1-9B-0414'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/glm-4-9b-0414@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'THUDM'
       AND model_name = 'GLM-4-9B-0414'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(1048576, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(131072, COALESCE(context_window_tokens, 1048576) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 131072))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/glm-5.2@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'zai-org'
       AND model_name = 'GLM-5.2'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(131072, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 131072) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/glm-4.5v@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'zai-org'
       AND model_name = 'GLM-4.5V'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(131072, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 131072) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/glm-4.5-air@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'zai-org'
       AND model_name = 'GLM-4.5-Air'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(202752, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(131072, COALESCE(context_window_tokens, 202752) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 131072))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/glm-5.1-pro@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/zai-org'
       AND model_name = 'GLM-5.1'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(524288, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 524288) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/seed-oss-36b-instruct@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'ByteDance-Seed'
       AND model_name = 'Seed-OSS-36B-Instruct'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(131072, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 131072) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/ling-flash-2.0@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'inclusionAI'
       AND model_name = 'Ling-flash-2.0'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(131072, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 131072) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/ling-mini-2.0@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'inclusionAI'
       AND model_name = 'Ling-mini-2.0'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(204800, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 204800) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/minimax-m2.5@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'MiniMaxAI'
       AND model_name = 'MiniMax-M2.5'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(204800, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 204800) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/minimax-m2.5-pro@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/MiniMaxAI'
       AND model_name = 'MiniMax-M2.5'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(32768, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(8192, COALESCE(max_output_tokens, 32768))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/kimi-k2.7-code@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'moonshotai'
       AND model_name = 'Kimi-K2.7-Code'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/nex-n2-pro@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'nex-agi'
       AND model_name = 'Nex-N2-Pro'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(262144, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(16384, COALESCE(context_window_tokens, 262144) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 16384))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/step-3.5-flash@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'stepfun-ai'
       AND model_name = 'Step-3.5-Flash'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(2048, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(1024, COALESCE(max_output_tokens, 2048))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/hunyuan-mt-7b@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'tencent'
       AND model_name = 'Hunyuan-MT-7B'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(131072, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(8192, COALESCE(context_window_tokens, 131072) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 8192))),
           capacity_source = COALESCE(capacity_source, c_source_profile),
           capability_profile_version = COALESCE(capability_profile_version, 'silicon/hunyuan-a13b-instruct@1')
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'tencent'
       AND model_name = 'Hunyuan-A13B-Instruct'
       AND delete_flag = c_active_flag
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    RAISE NOTICE 'Phase 1a catalog backfill (bare): % row(s) updated', v_total;
END $$;

-- ============================================================
-- Phase 1b: Tag already-filled rows whose ctx/max_out exactly match
--           the catalog with capability_profile_version. Upgrades
--           capacity_source from 'default' to 'profile' (values now
--           come from catalog, not system defaults). Preserves
--           'operator' and other explicit sources.
-- ============================================================

DO $$
DECLARE
    v_updated INTEGER := 0;
    v_total   INTEGER := 0;
    c_active_flag     CONSTANT TEXT := 'N';
    c_source_default  CONSTANT TEXT := 'default';
    c_source_profile  CONSTANT TEXT := 'profile';
BEGIN
    -- dashscope (4 entries)
    UPDATE nexent.model_record_t
       SET capability_profile_version = 'dashscope/qwen-plus@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'dashscope'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'qwen-plus'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 131072
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'dashscope/qwen-plus@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'dashscope/qwen-turbo@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'dashscope'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'qwen-turbo'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 1000000
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'dashscope/qwen-turbo@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'dashscope/qwen3.7-max@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'dashscope'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'qwen3.7-max'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 1000000
       AND max_output_tokens = 65536
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'dashscope/qwen3.7-max@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'dashscope/glm-5.1@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'dashscope'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'glm-5.1'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 200000
       AND max_output_tokens = 131072
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'dashscope/glm-5.1@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    -- deepseek (4 entries)
    UPDATE nexent.model_record_t
       SET capability_profile_version = 'deepseek/deepseek-chat@2',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'deepseek'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'deepseek-chat'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 1000000
       AND max_output_tokens = 384000
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'deepseek/deepseek-chat@2' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'deepseek/deepseek-reasoner@2',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'deepseek'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'deepseek-reasoner'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 1000000
       AND max_output_tokens = 384000
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'deepseek/deepseek-reasoner@2' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'deepseek/deepseek-v4-flash@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'deepseek'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'deepseek-v4-flash'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 1000000
       AND max_output_tokens = 384000
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'deepseek/deepseek-v4-flash@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'deepseek/deepseek-v4-pro@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'deepseek'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'deepseek-v4-pro'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 1000000
       AND max_output_tokens = 384000
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'deepseek/deepseek-v4-pro@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    -- openai (2 entries)
    UPDATE nexent.model_record_t
       SET capability_profile_version = 'openai/gpt-4o@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'openai'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'gpt-4o'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 128000
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'openai/gpt-4o@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'openai/gpt-4.1@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'openai'
       AND (model_repo IS NULL OR model_repo = '')
       AND model_name = 'gpt-4.1'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 1000000
       AND max_output_tokens = 32768
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'openai/gpt-4.1@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    -- silicon (56 entries)
    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3.6-27b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.6-27B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 65536
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3.6-27b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/kimi-k2.6@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/moonshotai'
       AND model_name = 'Kimi-K2.6'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 131072
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/kimi-k2.6@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/deepseek-v4-pro-sf@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-V4-Pro'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 1048576
       AND max_output_tokens = 384000
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/deepseek-v4-pro-sf@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/deepseek-v4-flash-sf@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-V4-Flash'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 1048576
       AND max_output_tokens = 384000
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/deepseek-v4-flash-sf@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/deepseek-v3.2@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-V3.2'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 164000
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/deepseek-v3.2@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/deepseek-v3.1-terminus@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-V3.1-Terminus'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 164000
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/deepseek-v3.1-terminus@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/deepseek-r1@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-R1'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 163840
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/deepseek-r1@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/deepseek-v3@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-V3'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 164000
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/deepseek-v3@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/deepseek-r1-0528-qwen3-8b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'deepseek-ai'
       AND model_name = 'DeepSeek-R1-0528-Qwen3-8B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 131072
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/deepseek-r1-0528-qwen3-8b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/deepseek-v3.2-pro@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/deepseek-ai'
       AND model_name = 'DeepSeek-V3.2'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 164000
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/deepseek-v3.2-pro@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/deepseek-v3.1-terminus-pro@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/deepseek-ai'
       AND model_name = 'DeepSeek-V3.1-Terminus'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 164000
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/deepseek-v3.1-terminus-pro@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/deepseek-r1-pro@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/deepseek-ai'
       AND model_name = 'DeepSeek-R1'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 163840
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/deepseek-r1-pro@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/deepseek-v3-pro@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/deepseek-ai'
       AND model_name = 'DeepSeek-V3'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 164000
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/deepseek-v3-pro@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3.6-35b-a3b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.6-35B-A3B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3.6-35b-a3b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3.5-397b-a17b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-397B-A17B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3.5-397b-a17b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3.5-122b-a10b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-122B-A10B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3.5-122b-a10b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3.5-35b-a3b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-35B-A3B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3.5-35b-a3b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3.5-27b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-27B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3.5-27b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3.5-9b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-9B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3.5-9b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3.5-4b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3.5-4B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3.5-4b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-vl-32b-instruct@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-32B-Instruct'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-vl-32b-instruct@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-vl-32b-thinking@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-32B-Thinking'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 32768
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-vl-32b-thinking@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-vl-8b-instruct@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-8B-Instruct'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-vl-8b-instruct@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-vl-8b-thinking@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-8B-Thinking'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 32768
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-vl-8b-thinking@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-vl-30b-a3b-instruct@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-30B-A3B-Instruct'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-vl-30b-a3b-instruct@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-vl-30b-a3b-thinking@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-VL-30B-A3B-Thinking'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 32768
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-vl-30b-a3b-thinking@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-omni-30b-a3b-instruct@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-Omni-30B-A3B-Instruct'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 32768
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-omni-30b-a3b-instruct@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-omni-30b-a3b-thinking@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-Omni-30B-A3B-Thinking'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 32768
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-omni-30b-a3b-thinking@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-omni-30b-a3b-captioner@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-Omni-30B-A3B-Captioner'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 32768
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-omni-30b-a3b-captioner@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-coder-30b-a3b-instruct@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-Coder-30B-A3B-Instruct'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 65536
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-coder-30b-a3b-instruct@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-30b-a3b-instruct-2507@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-30B-A3B-Instruct-2507'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-30b-a3b-instruct-2507@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-32b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-32B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 131072
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-32b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-14b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-14B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 131072
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-14b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen3-8b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen3-8B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 131072
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen3-8b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen2.5-72b-instruct-128k@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen2.5-72B-Instruct-128K'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 131072
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen2.5-72b-instruct-128k@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen2.5-72b-instruct@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen2.5-72B-Instruct'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 32768
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen2.5-72b-instruct@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen2.5-32b-instruct@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen2.5-32B-Instruct'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 32768
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen2.5-32b-instruct@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen2.5-14b-instruct@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen2.5-14B-Instruct'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 32768
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen2.5-14b-instruct@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/qwen2.5-7b-instruct@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Qwen'
       AND model_name = 'Qwen2.5-7B-Instruct'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 32768
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/qwen2.5-7b-instruct@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/glm-4-32b-0414@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'THUDM'
       AND model_name = 'GLM-4-32B-0414'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 32768
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/glm-4-32b-0414@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/glm-z1-9b-0414@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'THUDM'
       AND model_name = 'GLM-Z1-9B-0414'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 32768
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/glm-z1-9b-0414@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/glm-4-9b-0414@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'THUDM'
       AND model_name = 'GLM-4-9B-0414'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 32768
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/glm-4-9b-0414@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/glm-5.2@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'zai-org'
       AND model_name = 'GLM-5.2'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 1048576
       AND max_output_tokens = 131072
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/glm-5.2@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/glm-4.5v@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'zai-org'
       AND model_name = 'GLM-4.5V'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 131072
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/glm-4.5v@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/glm-4.5-air@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'zai-org'
       AND model_name = 'GLM-4.5-Air'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 131072
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/glm-4.5-air@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/glm-5.1-pro@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/zai-org'
       AND model_name = 'GLM-5.1'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 202752
       AND max_output_tokens = 131072
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/glm-5.1-pro@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/seed-oss-36b-instruct@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'ByteDance-Seed'
       AND model_name = 'Seed-OSS-36B-Instruct'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 524288
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/seed-oss-36b-instruct@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/ling-flash-2.0@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'inclusionAI'
       AND model_name = 'Ling-flash-2.0'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 131072
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/ling-flash-2.0@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/ling-mini-2.0@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'inclusionAI'
       AND model_name = 'Ling-mini-2.0'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 131072
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/ling-mini-2.0@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/minimax-m2.5@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'MiniMaxAI'
       AND model_name = 'MiniMax-M2.5'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 204800
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/minimax-m2.5@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/minimax-m2.5-pro@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'Pro/MiniMaxAI'
       AND model_name = 'MiniMax-M2.5'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 204800
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/minimax-m2.5-pro@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/kimi-k2.7-code@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'moonshotai'
       AND model_name = 'Kimi-K2.7-Code'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 32768
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/kimi-k2.7-code@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/nex-n2-pro@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'nex-agi'
       AND model_name = 'Nex-N2-Pro'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/nex-n2-pro@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/step-3.5-flash@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'stepfun-ai'
       AND model_name = 'Step-3.5-Flash'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 262144
       AND max_output_tokens = 16384
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/step-3.5-flash@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/hunyuan-mt-7b@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'tencent'
       AND model_name = 'Hunyuan-MT-7B'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 32768
       AND max_output_tokens = 2048
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/hunyuan-mt-7b@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET capability_profile_version = 'silicon/hunyuan-a13b-instruct@1',
           capacity_source = CASE WHEN capacity_source = c_source_default THEN c_source_profile ELSE capacity_source END
     WHERE LOWER(model_factory) = 'silicon'
       AND model_repo = 'tencent'
       AND model_name = 'Hunyuan-A13B-Instruct'
       AND delete_flag = c_active_flag
       AND context_window_tokens = 131072
       AND max_output_tokens = 8192
       AND (capability_profile_version IS NULL OR (capability_profile_version = 'silicon/hunyuan-a13b-instruct@1' AND capacity_source = c_source_default));
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    RAISE NOTICE 'Phase 1b catalog tag (matching filled): % row(s) updated', v_total;
END $$;

-- ============================================================
-- Phase 2: Safe defaults for remaining bare LLM/VLM rows
-- ============================================================

DO $$
DECLARE
    v_updated INTEGER := 0;
    c_active_flag     CONSTANT TEXT := 'N';
    c_source_default  CONSTANT TEXT := 'default';
BEGIN
    UPDATE nexent.model_record_t
       SET context_window_tokens = COALESCE(context_window_tokens,
           GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)),
           max_output_tokens = COALESCE(max_output_tokens,
           LEAST(4096, COALESCE(context_window_tokens, 32768) - 1)),
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens,
           LEAST(4096, COALESCE(max_output_tokens, 4096))),
           capacity_source = COALESCE(capacity_source, c_source_default)
     WHERE delete_flag = c_active_flag
       AND COALESCE(model_type, 'llm') IN ('llm', 'vlm')
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RAISE NOTICE 'Safe defaults: % LLM/VLM row(s) backfilled', v_updated;
END $$;

-- ============================================================
-- Phase 3: Clamp default_output_reserve_tokens to max_output_tokens
-- ============================================================

DO $$
DECLARE
    v_updated INTEGER := 0;
    c_active_flag     CONSTANT TEXT := 'N';
BEGIN
    UPDATE nexent.model_record_t
       SET default_output_reserve_tokens = max_output_tokens
     WHERE delete_flag = c_active_flag
       AND default_output_reserve_tokens IS NOT NULL
       AND max_output_tokens IS NOT NULL
       AND default_output_reserve_tokens > max_output_tokens;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RAISE NOTICE 'reserve clamp: % row(s) updated', v_updated;
END $$;

-- Source migration: v2.2.2_0629_conversation_message_unit_status_and_clean.sql

-- Migration: Add status / unit_status fields to support streaming persistence
-- Date: 2026-06-29
-- Description: Allow per-message and per-unit lifecycle tracking so the
-- frontend can recover partial agent runs when the SSE connection is lost

SET search_path TO nexent;

BEGIN;

-- Message-level lifecycle. Assistant messages start as 'pending' / 'streaming'
-- and transition to one of completed / failed / stopped. User messages default
-- to 'completed' (existing rows are backfilled below).
ALTER TABLE nexent.conversation_message_t
    ADD COLUMN IF NOT EXISTS status VARCHAR(30);

COMMENT ON COLUMN nexent.conversation_message_t.status IS
    'Lifecycle status: pending / streaming / completed / failed / stopped.';

-- Unit-level lifecycle. Once a unit is fully persisted we mark it 'completed';
-- while the boundary is still being detected it remains 'streaming'.
ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS unit_status VARCHAR(30);

COMMENT ON COLUMN nexent.conversation_message_unit_t.unit_status IS
    'Lifecycle status: streaming (still aggregating) or completed (fully persisted).';

-- Index for incremental recovery queries (since_message_unit_id filters).
CREATE INDEX IF NOT EXISTS idx_message_unit_message_id_unit_id
    ON nexent.conversation_message_unit_t (message_id, unit_id);

-- Cleanup stale deep_thinking units.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name = 'conversation_message_unit_t'
          AND column_name = 'unit_status'
    ) THEN
        DELETE FROM nexent.conversation_message_unit_t
        WHERE unit_type = 'model_output_deep_thinking'
          AND unit_status IS NULL;
    END IF;
END $$;

-- Cleanup corrupted records of thinking units
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name = 'conversation_message_unit_t'
          AND column_name = 'unit_status'
    ) THEN
        DELETE FROM nexent.conversation_message_unit_t
        WHERE unit_type = 'model_output_thinking'
          AND unit_content = ''
          AND unit_status IS NULL;
    END IF;
END $$;

COMMIT;
