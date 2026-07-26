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
