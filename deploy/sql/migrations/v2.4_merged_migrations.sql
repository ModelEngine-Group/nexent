-- Nexent merged SQL migrations: v2.4
-- This file is generated from historical migration files.

-- Source migration: v2.4.0_0710_add_kb_quota_column.sql

-- Add quota_limit_bytes column to knowledge_record_t for per-KB soft storage quota
-- NULL = unlimited (shares tenant pool freely)

ALTER TABLE nexent.knowledge_record_t ADD COLUMN IF NOT EXISTS quota_limit_bytes BIGINT;

-- Source migration: v2.4.0_0713_memory_records_phase2.sql

-- ============================================================================
-- Phase 2 Memory Architecture: memory_records_t / memory_retrieval_hits_t
-- ============================================================================
-- Authoritative memory store (tenant/user/agent) and per-hit retrieval log.
-- Primary keys use PostgreSQL `SERIAL4` shorthand (implicit sequence +
-- NOT NULL + PRIMARY KEY); isolation columns remain varchar for cross-table
-- consistency with `memory_user_config_t`.

CREATE TABLE IF NOT EXISTS nexent.memory_records_t (
    memory_id          SERIAL4 PRIMARY KEY,
    tenant_id          varchar(100),
    user_id            varchar(100),
    agent_id           varchar(100),
    conversation_id    varchar(100),
    layer              varchar(30)  NOT NULL,
    memory_type        varchar(30),
    status             varchar(30)  NOT NULL DEFAULT 'active',
    content            text         NOT NULL,
    concept_tags       text[],
    es_index_name      varchar(255),
    create_time        timestamp DEFAULT CURRENT_TIMESTAMP,
    update_time        timestamp DEFAULT CURRENT_TIMESTAMP,
    created_by         varchar(100),
    updated_by         varchar(100),
    delete_flag        varchar(1)   NOT NULL DEFAULT 'N',
    idempotency_key    varchar(128) NOT NULL,
    recall_count       int4         NOT NULL DEFAULT 0,
    daily_count        int4         NOT NULL DEFAULT 0,
    grounded_count     int4         NOT NULL DEFAULT 0,
    last_recalled_at   timestamp,
    query_hashes       text[],
    recall_days        text[],
    light_hits         int4         NOT NULL DEFAULT 0,
    rem_hits           int4         NOT NULL DEFAULT 0,
    last_light_at      timestamp,
    last_rem_at        timestamp
);
ALTER TABLE nexent.memory_records_t OWNER TO "root";

COMMENT ON COLUMN nexent.memory_records_t.memory_id IS 'Auto-incremented memory primary key (serial4).';
COMMENT ON COLUMN nexent.memory_records_t.tenant_id IS 'Tenant ID (isolation key).';
COMMENT ON COLUMN nexent.memory_records_t.user_id IS 'User ID (isolation key for user/agent layers).';
COMMENT ON COLUMN nexent.memory_records_t.agent_id IS 'Agent ID (isolation key for agent short-term layer).';
COMMENT ON COLUMN nexent.memory_records_t.conversation_id IS 'Conversation ID (further isolation key for agent).';
COMMENT ON COLUMN nexent.memory_records_t.layer IS 'Memory layer: tenant | user | agent.';
COMMENT ON COLUMN nexent.memory_records_t.memory_type IS 'Memory type: long_term | short_term.';
COMMENT ON COLUMN nexent.memory_records_t.status IS 'Status: active | archived | disabled.';
COMMENT ON COLUMN nexent.memory_records_t.content IS 'Memory content.';
COMMENT ON COLUMN nexent.memory_records_t.concept_tags IS 'Optional concept tags from Dreaming REM phase.';
COMMENT ON COLUMN nexent.memory_records_t.es_index_name IS 'Elasticsearch index for agent short-term memory (mem_<model>_<dim>); null for PG-only layers.';
COMMENT ON COLUMN nexent.memory_records_t.create_time IS 'Creation time, audit field.';
COMMENT ON COLUMN nexent.memory_records_t.update_time IS 'Update time, audit field.';
COMMENT ON COLUMN nexent.memory_records_t.created_by IS 'Creator ID, audit field.';
COMMENT ON COLUMN nexent.memory_records_t.updated_by IS 'Last updater ID, audit field.';
COMMENT ON COLUMN nexent.memory_records_t.delete_flag IS 'Soft delete flag (Y/N).';
COMMENT ON COLUMN nexent.memory_records_t.idempotency_key IS 'Idempotency key for write deduplication.';
COMMENT ON COLUMN nexent.memory_records_t.recall_count IS 'Total recall hit count.';
COMMENT ON COLUMN nexent.memory_records_t.daily_count IS 'Recall hit count for the most recent active day.';
COMMENT ON COLUMN nexent.memory_records_t.grounded_count IS 'Count of grounded (verified) recalls.';
COMMENT ON COLUMN nexent.memory_records_t.last_recalled_at IS 'Most recent recall timestamp.';
COMMENT ON COLUMN nexent.memory_records_t.query_hashes IS 'Hashes of queries that recalled this memory.';
COMMENT ON COLUMN nexent.memory_records_t.recall_days IS 'ISO date strings of recall days.';
COMMENT ON COLUMN nexent.memory_records_t.light_hits IS 'Light Sleep phase hit count.';
COMMENT ON COLUMN nexent.memory_records_t.rem_hits IS 'REM Sleep phase hit count.';
COMMENT ON COLUMN nexent.memory_records_t.last_light_at IS 'Last Light Sleep timestamp.';
COMMENT ON COLUMN nexent.memory_records_t.last_rem_at IS 'Last REM Sleep timestamp.';
COMMENT ON TABLE  nexent.memory_records_t IS 'Authoritative store for tenant/user/agent memory (Phase 2).';

CREATE INDEX IF NOT EXISTS idx_memory_records_tenant
    ON nexent.memory_records_t (tenant_id);
CREATE INDEX IF NOT EXISTS idx_memory_records_user
    ON nexent.memory_records_t (tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_memory_records_agent
    ON nexent.memory_records_t (tenant_id, user_id, agent_id, conversation_id);
CREATE INDEX IF NOT EXISTS idx_memory_records_idempotency
    ON nexent.memory_records_t (tenant_id, idempotency_key);
CREATE INDEX IF NOT EXISTS idx_memory_records_status
    ON nexent.memory_records_t (tenant_id, user_id, layer, status);

CREATE TABLE IF NOT EXISTS nexent.memory_retrieval_hits_t (
    hit_id             SERIAL4 PRIMARY KEY,
    tenant_id          varchar(100),
    user_id            varchar(100),
    agent_id           varchar(100),
    conversation_id    varchar(100),
    memory_id          int4,
    query_text         text,
    query_hash         varchar(128),
    retrieval_score    numeric(38, 18),
    source             varchar(100) NOT NULL DEFAULT 'nexent',
    occurred_at        timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    day                varchar(100),
    grounded           boolean NOT NULL DEFAULT false,
    create_time        timestamp DEFAULT CURRENT_TIMESTAMP,
    update_time        timestamp DEFAULT CURRENT_TIMESTAMP,
    created_by         varchar(100),
    updated_by         varchar(100),
    delete_flag        varchar(1)   NOT NULL DEFAULT 'N'
);
ALTER TABLE nexent.memory_retrieval_hits_t OWNER TO "root";

COMMENT ON COLUMN nexent.memory_retrieval_hits_t.hit_id IS 'Hit primary key (serial4).';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.tenant_id IS 'Tenant ID.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.user_id IS 'User ID.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.agent_id IS 'Agent ID.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.conversation_id IS 'Conversation ID.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.memory_id IS 'Recalled memory id (null on miss rows).';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.query_text IS 'Original search query text.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.query_hash IS 'Stable hash of the query text.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.retrieval_score IS 'Similarity score reported by the backend.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.source IS 'Hit origin: nexent | external_provider.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.occurred_at IS 'Time the hit was recorded.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.day IS 'ISO date string (occurred_at::date).';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.grounded IS 'Whether the hit was verified/grounded.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.create_time IS 'Row creation time.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.update_time IS 'Row last update time.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.created_by IS 'User that created the row.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.updated_by IS 'User that last updated the row.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.delete_flag IS 'Soft delete flag (N = active, Y = deleted).';
COMMENT ON TABLE  nexent.memory_retrieval_hits_t IS 'Per-hit memory retrieval log; consumed by Dreaming scheduler.';

CREATE INDEX IF NOT EXISTS idx_memory_retrieval_hits_memory
    ON nexent.memory_retrieval_hits_t (memory_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_memory_retrieval_hits_tenant_user_agent
    ON nexent.memory_retrieval_hits_t (tenant_id, user_id, agent_id, day);

CREATE OR REPLACE FUNCTION nexent.update_memory_records_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_memory_records_update_time_trigger ON nexent.memory_records_t;
CREATE TRIGGER update_memory_records_update_time_trigger
BEFORE UPDATE ON nexent.memory_records_t
FOR EACH ROW
EXECUTE FUNCTION nexent.update_memory_records_update_time();

COMMENT ON TRIGGER update_memory_records_update_time_trigger ON nexent.memory_records_t IS 'Trigger to call update_memory_records_update_time function before each update on memory_records_t table';

-- Trigger to keep memory_retrieval_hits_t.update_time fresh on UPDATE.
CREATE OR REPLACE FUNCTION nexent.update_memory_retrieval_hits_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_memory_retrieval_hits_update_time_trigger ON nexent.memory_retrieval_hits_t;
CREATE TRIGGER update_memory_retrieval_hits_update_time_trigger
BEFORE UPDATE ON nexent.memory_retrieval_hits_t
FOR EACH ROW
EXECUTE FUNCTION nexent.update_memory_retrieval_hits_update_time();

COMMENT ON TRIGGER update_memory_retrieval_hits_update_time_trigger ON nexent.memory_retrieval_hits_t IS 'Trigger to call update_memory_retrieval_hits_update_time function before each update on memory_retrieval_hits_t table';

-- Source migration: v2.4.0_0716_add_mcp_permissions_and_sharing.sql

-- Migration: Add permission and sharing fields to MCP tables
-- Date: 2026-07-16
-- Description:
--   - mcp_record_t: add group_ids, ingroup_permission, shared_fields
--   - mcp_market_record_t: add group_ids, ingroup_permission, shared_fields
--   Both target the same commit to keep the migration atomic.

SET search_path TO nexent;

BEGIN;

-- -------------------------------------------------------------------------
-- mcp_market_record_t — group-based access control
-- -------------------------------------------------------------------------
ALTER TABLE nexent.mcp_market_record_t
    ADD COLUMN IF NOT EXISTS group_ids VARCHAR,
    ADD COLUMN IF NOT EXISTS ingroup_permission VARCHAR(30) DEFAULT 'READ_ONLY';

COMMENT ON COLUMN nexent.mcp_market_record_t.group_ids IS
    'Comma-separated group IDs that can access this MCP';
COMMENT ON COLUMN nexent.mcp_market_record_t.ingroup_permission IS
    'In-group permission: EDIT, READ_ONLY, PRIVATE';

-- -------------------------------------------------------------------------
-- mcp_market_record_t — shared-fields snapshot at submission time
-- -------------------------------------------------------------------------
ALTER TABLE nexent.mcp_market_record_t
    ADD COLUMN IF NOT EXISTS shared_fields JSON;

COMMENT ON COLUMN nexent.mcp_market_record_t.shared_fields IS
    'Snapshot of shared_fields at submission time';

-- -------------------------------------------------------------------------
-- mcp_record_t — group-based access control
-- -------------------------------------------------------------------------
ALTER TABLE nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS group_ids VARCHAR,
    ADD COLUMN IF NOT EXISTS ingroup_permission VARCHAR(30) DEFAULT 'READ_ONLY';

COMMENT ON COLUMN nexent.mcp_record_t.group_ids IS
    'Comma-separated group IDs that can access this MCP';
COMMENT ON COLUMN nexent.mcp_record_t.ingroup_permission IS
    'In-group permission: EDIT, READ_ONLY, PRIVATE';

-- -------------------------------------------------------------------------
-- mcp_record_t — field-level sharing flags
-- -------------------------------------------------------------------------
ALTER TABLE nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS shared_fields JSON;

COMMENT ON COLUMN nexent.mcp_record_t.shared_fields IS
    'JSON object of field-level sharing flags (e.g. {"serverUrl": true, "authorizationToken": false})';

-- -------------------------------------------------------------------------
-- Grant EDIT permission to existing public MCPs
-- Existing MCPs with NULL group_ids have no group restrictions
-- and should be editable by all tenant users.
-- -------------------------------------------------------------------------
UPDATE nexent.mcp_record_t
SET ingroup_permission = 'EDIT'
WHERE group_ids IS NULL
  AND delete_flag != 'Y';

-- -------------------------------------------------------------------------
-- Fix mcp_market_record_t unique index: use (tenant_id, mcp_name) instead
-- of (mcp_name) to prevent cross-tenant name conflicts.
-- -------------------------------------------------------------------------
DROP INDEX IF EXISTS nexent.uq_mcp_market_name_active;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_market_name_active
    ON nexent.mcp_market_record_t (tenant_id, mcp_name)
    WHERE delete_flag = 'N' AND review_status = 'shared';

COMMIT;

-- Source migration: v2.4.0_0720_add_agent_is_main_agent.sql

-- Add a main-agent flag to tenant agents.
ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS is_main_agent BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.is_main_agent
    IS 'Whether this agent is a main agent';

-- Source migration: v2.4.0_0721_add_newchat_left_nav_permissions.sql

BEGIN;
INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype,
    parent_key
)
VALUES
    (1114, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/newchat', NULL),
    (1213, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/newchat', NULL),
    (1305, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/newchat', NULL),
    (1413, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/newchat', NULL),
    (1512, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/newchat', NULL)
ON CONFLICT (role_permission_id) DO NOTHING;
COMMIT;

-- Source migration: v2.4.0_0722_add_agent_automation.sql

-- Add durable scheduled agent tasks, run history, chat proposals, and navigation permissions.

SET search_path TO nexent;

BEGIN;

CREATE TABLE IF NOT EXISTS nexent.agent_automation_task_t (
    task_id BIGSERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    conversation_id BIGINT NOT NULL,
    agent_id BIGINT NOT NULL,
    agent_version_no INTEGER,
    title VARCHAR(255) NOT NULL,
    instruction TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    source VARCHAR(32) NOT NULL,
    schedule_mode VARCHAR(16) NOT NULL,
    schedule_rule_type VARCHAR(16) NOT NULL,
    schedule_expr TEXT,
    schedule_config JSONB NOT NULL,
    capability_requirements JSONB,
    capability_bindings JSONB,
    runtime_snapshot JSONB,
    timezone VARCHAR(64) NOT NULL,
    next_fire_at TIMESTAMPTZ,
    last_fire_at TIMESTAMPTZ,
    fire_count INTEGER NOT NULL DEFAULT 0,
    last_run_status VARCHAR(32),
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    timeout_seconds INTEGER NOT NULL,
    overlap_policy VARCHAR(16) NOT NULL,
    misfire_policy VARCHAR(16) NOT NULL,
    lock_owner VARCHAR(128),
    lock_until TIMESTAMPTZ,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE IF NOT EXISTS nexent.agent_automation_run_t (
    run_id BIGSERIAL PRIMARY KEY NOT NULL,
    task_id BIGINT NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    conversation_id BIGINT NOT NULL,
    scheduled_fire_at TIMESTAMPTZ NOT NULL,
    actual_fire_at TIMESTAMPTZ,
    trigger_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    generated_prompt TEXT,
    user_message_id BIGINT,
    assistant_message_id BIGINT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    duration_ms BIGINT,
    error_code VARCHAR(64),
    error_message TEXT,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE IF NOT EXISTS nexent.agent_automation_proposal_t (
    proposal_id BIGSERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    conversation_id BIGINT NOT NULL,
    agent_id BIGINT NOT NULL,
    proposed_task JSONB NOT NULL,
    capability_resolution JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS idx_agent_automation_due
    ON nexent.agent_automation_task_t (status, next_fire_at)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_agent_automation_owner
    ON nexent.agent_automation_task_t (tenant_id, user_id, status)
    WHERE delete_flag = 'N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_automation_conversation_active
    ON nexent.agent_automation_task_t (conversation_id)
    WHERE delete_flag = 'N' AND status <> 'DELETED';

CREATE INDEX IF NOT EXISTS idx_agent_automation_run_task
    ON nexent.agent_automation_run_t (task_id, scheduled_fire_at)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_agent_automation_run_conversation
    ON nexent.agent_automation_run_t (conversation_id, status)
    WHERE delete_flag = 'N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_automation_active_occurrence
    ON nexent.agent_automation_run_t (task_id, scheduled_fire_at)
    WHERE delete_flag = 'N'
      AND trigger_type = 'SCHEDULED'
      AND status IN ('QUEUED', 'RUNNING');

ALTER TABLE nexent.agent_automation_run_t
    DROP COLUMN IF EXISTS capability_check;

CREATE INDEX IF NOT EXISTS idx_agent_automation_proposal_owner
    ON nexent.agent_automation_proposal_t (tenant_id, user_id, status)
    WHERE delete_flag = 'N';

DELETE FROM nexent.role_permission_t
WHERE role_permission_id BETWEEN 1512 AND 1517;

-- Keep each permission in the ID range assigned to its role.
INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype,
    parent_key
)
VALUES
    (1115, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-tasks', NULL),
    (1214, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-tasks', NULL),
    (1306, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-tasks', NULL),
    (1414, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-tasks', NULL),
    (1513, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-tasks', NULL)
ON CONFLICT (role_permission_id) DO NOTHING;

COMMIT;

-- Source migration: v2.4.0_0722_add_skill_permission_and_repository_snapshots.sql

-- Migration: Add tenant-scoped skill uniqueness and group permissions; allow repository snapshots by status
-- Date: 2026-07-22
-- Description: Align skill ownership and repository status behavior with agent repository semantics.

SET search_path TO nexent;

ALTER TABLE IF EXISTS nexent.ag_skill_info_t
    DROP CONSTRAINT IF EXISTS ag_skill_info_t_skill_name_key;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM nexent.ag_skill_info_t
        WHERE tenant_id IS NOT NULL
          AND delete_flag = 'N'
        GROUP BY tenant_id, skill_name
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot enforce tenant-scoped Skill names: duplicate active (tenant_id, skill_name) rows exist';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM nexent.ag_skill_info_t
        WHERE tenant_id IS NULL
          AND delete_flag = 'N'
        GROUP BY skill_name
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot enforce global template Skill names: duplicate active skill_name rows exist';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_info_tenant_name_active
    ON nexent.ag_skill_info_t (tenant_id, skill_name)
    WHERE tenant_id IS NOT NULL AND delete_flag = 'N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_info_global_name_active
    ON nexent.ag_skill_info_t (skill_name)
    WHERE tenant_id IS NULL AND delete_flag = 'N';

COMMENT ON COLUMN nexent.ag_skill_info_t.skill_name IS
    'Skill name, unique among active skills within its tenant scope';

ALTER TABLE IF EXISTS nexent.ag_skill_info_t
    ADD COLUMN IF NOT EXISTS group_ids VARCHAR,
    ADD COLUMN IF NOT EXISTS ingroup_permission VARCHAR(30);

COMMENT ON COLUMN nexent.ag_skill_info_t.group_ids IS 'Skill group IDs list';
COMMENT ON COLUMN nexent.ag_skill_info_t.ingroup_permission IS 'In-group permission: EDIT, READ_ONLY, PRIVATE';

WITH tenant_groups AS (
    SELECT
        tenant_id,
        string_agg(group_id::text, ',' ORDER BY group_id) AS group_ids
    FROM nexent.tenant_group_info_t
    WHERE delete_flag = 'N'
    GROUP BY tenant_id
)
UPDATE nexent.ag_skill_info_t skill
SET group_ids = tenant_groups.group_ids
FROM tenant_groups
WHERE skill.tenant_id = tenant_groups.tenant_id
  AND skill.delete_flag = 'N'
  AND skill.tenant_id IS NOT NULL
  AND (skill.group_ids IS NULL OR skill.group_ids = '');

UPDATE nexent.ag_skill_info_t
SET ingroup_permission = 'EDIT'
WHERE delete_flag = 'N'
  AND tenant_id IS NOT NULL
  AND (ingroup_permission IS NULL OR ingroup_permission = '');

DROP INDEX IF EXISTS nexent.uq_skill_repository_skill_active;
DROP INDEX IF EXISTS nexent.uq_skill_repository_skill_shared_active;
DROP INDEX IF EXISTS nexent.uq_skill_repository_skill_pending_active;

CREATE INDEX IF NOT EXISTS idx_skill_repository_skill_status_delete
    ON nexent.ag_skill_repository_t (publisher_tenant_id, skill_id, status, delete_flag);

COMMENT ON COLUMN nexent.ag_skill_repository_t.skill_id IS
    'Source skill ID from ag_skill_info_t; multiple active snapshots may exist across statuses';

-- Source migration: v2.4.0_0723_add_aidp_kb_permission.sql

-- ============================================================
-- Add aidp_kb_permission_t table for AIDP knowledge base permissions
-- Migration Date: 2026-07-23
-- Description:
--   P0 data layer for the AIDP permission redesign (v7.1).
--   - Stores one record per KB that has been claimed into Nexent.
--   - UNIQUE(kb_id) WHERE delete_flag='N' prevents concurrent active duplicates.
--   - group_ids uses JSONB for type safety and indexable intersection queries.
--   - resource_status tracks lifecycle so the API can surface UNKNOWN/ORPHANED
--     KBs without silently hiding them.
--   - kds_name caches the AIDP display name so the LLM tool can resolve
--     human-readable names to kds_ids without an extra AIDP round-trip.
-- Idempotent: every DDL uses IF NOT EXISTS so re-running this migration is safe.
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS nexent.aidp_kb_permission_t (
    id                  BIGSERIAL PRIMARY KEY,
    kb_id               VARCHAR(128) NOT NULL,
    kds_name            VARCHAR(128),
    owner_user_id       VARCHAR(100) NOT NULL,
    tenant_id           VARCHAR(100) NOT NULL,
    ingroup_permission  VARCHAR(30)  NOT NULL DEFAULT 'READ_ONLY',
    group_ids           JSONB        NOT NULL DEFAULT '[]'::jsonb,
    resource_status     VARCHAR(30)  NOT NULL DEFAULT 'ACTIVE',
    create_time         TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time         TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by          VARCHAR(100),
    updated_by          VARCHAR(100),
    delete_flag         VARCHAR(1)   NOT NULL DEFAULT 'N'
);

-- Active-record uniqueness: only one live row per kbs_id.
-- After a soft delete the constraint releases the kb_id, allowing re-creation.
CREATE UNIQUE INDEX IF NOT EXISTS uq_aidp_kb_permission_active_kb
    ON nexent.aidp_kb_permission_t (kb_id)
    WHERE delete_flag = 'N';

-- Tenant and ownership lookup indexes; partial on active rows only.
CREATE INDEX IF NOT EXISTS idx_aidp_perm_tenant
    ON nexent.aidp_kb_permission_t (tenant_id)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_aidp_perm_user
    ON nexent.aidp_kb_permission_t (owner_user_id, tenant_id)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_aidp_perm_kb
    ON nexent.aidp_kb_permission_t (kb_id)
    WHERE delete_flag = 'N';

-- JSONB GIN index supports `group_ids @> '[1,2]'::jsonb` intersection queries
-- that the permission service uses to determine KB accessibility.
CREATE INDEX IF NOT EXISTS idx_aidp_perm_group_ids_gin
    ON nexent.aidp_kb_permission_t USING GIN (group_ids)
    WHERE delete_flag = 'N';

COMMENT ON TABLE  nexent.aidp_kb_permission_t IS
    'AIDP knowledge base permission records. Each row represents a KB under Nexent management.';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.kb_id IS
    'kds_id returned by AIDP, globally unique within AIDP system (AIDP guarantees this).';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.owner_user_id IS
    'Nexent user_id of the KB creator (Nexent account that called the AIDP create API).';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.tenant_id IS
    'Nexent tenant_id; combined with delete_flag this is the only valid query key for multi-tenant isolation.';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.ingroup_permission IS
    'Permission level for authorized groups: EDIT / READ_ONLY / PRIVATE.';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.group_ids IS
    'JSON array of Nexent group IDs authorized to access this KB. Empty array means no group access.';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.resource_status IS
    'Resource lifecycle status: CREATING / ACTIVE / DELETE_PENDING / ORPHANED / UNAVAILABLE.';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.delete_flag IS
    'Y / N. Active rows are N. Soft delete flips this to Y so the active uniqueness constraint releases the kb_id.';

-- Migration-safe column add: covers tables created before kds_name was introduced.
-- Changing this file's checksum causes the runner to re-execute; IF NOT EXISTS makes it safe.
ALTER TABLE nexent.aidp_kb_permission_t ADD COLUMN IF NOT EXISTS kds_name VARCHAR(128);

COMMENT ON COLUMN nexent.aidp_kb_permission_t.kds_name IS
    'AIDP knowledge base display name (kds_name), cached at creation time so the LLM tool can resolve human-readable names to kds_ids without an AIDP round-trip.';

COMMIT;

-- Source migration: v2.4.0_0723_add_conversation_chat_mode_and unit_tool_call.sql

-- Persist the UI chat mode (planning vs. execution) for each conversation so
-- switching threads can restore the toggle without re-inferring it from units.

ALTER TABLE nexent.conversation_record_t
  ADD COLUMN IF NOT EXISTS chat_mode varchar(16) NOT NULL DEFAULT 'execution';

COMMENT ON COLUMN nexent.conversation_record_t.chat_mode IS
  'UI chat mode of the conversation. Allowed values: planning, execution.';

SET search_path TO nexent;

ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS tool_call_id VARCHAR(36);

COMMENT ON COLUMN nexent.conversation_message_unit_t.tool_call_id IS
    'Unique ID of the originating tool invocation, used to attribute side-channel units to the correct tool call during parallel execution.';

-- Source migration: v2.4.0_0723_cleanup_aidp_tool_credentials.sql

-- ============================================================
-- Strip legacy AIDP credentials from tool instance params.
-- Migration Date: 2026-07-23
-- Description:
--   Earlier versions of the aidp_search tool accepted ``server_url`` and
--   ``api_key`` via the per-instance params (sometimes stored in plain
--   text in browser localStorage). The v7.1 permission redesign makes
--   Nexent the sole owner of those credentials, sourced from the
--   AIDP_SERVER_URL / AIDP_API_KEY environment variables.
--
--   This migration removes any persisted ``server_url`` / ``api_key``
--   entries from ``ag_tool_instance_t.params`` for ``aidp_search`` tool
--   instances so historical rows do not leak the old value.
--
-- Idempotent: rewrites params only when at least one of the keys is
-- present; safe to re-run.
-- ============================================================

BEGIN;

UPDATE nexent.ag_tool_instance_t instance
SET params = (
    REPLACE(
        REPLACE(instance.params::text, '"server_url"', '"_removed_server_url"'),
        '"api_key"', '"_removed_api_key"'
    )::jsonb - '_removed_server_url' - '_removed_api_key'
)::text::json
FROM nexent.ag_tool_info_t tool
WHERE instance.tool_id = tool.tool_id
  AND tool.name = 'aidp_search'
  AND instance.delete_flag = 'N'
  AND instance.params IS NOT NULL
  AND (
      instance.params::text LIKE '%server_url%'
      OR instance.params::text LIKE '%api_key%'
  );

-- Validation query (manual):
--   SELECT COUNT(*) FROM nexent.ag_tool_instance_t instance
--   JOIN nexent.ag_tool_info_t tool ON instance.tool_id = tool.tool_id
--   WHERE tool.name = 'aidp_search'
--     AND instance.delete_flag = 'N'
--     AND instance.params::text LIKE '%server_url%';

COMMIT;

-- Source migration: v2.4.0_0725_rename_mem_agent_permission_to_mem_tenant.sql

-- Migration: Rename tenant-memory permissions from MEM.AGENT to MEM.TENANT
-- Date: 2026-07-25
-- Description: Align permission names with the tenant memory layer they govern.

SET search_path TO nexent;

UPDATE nexent.role_permission_t
SET permission_type = 'MEM.TENANT'
WHERE permission_type = 'MEM.AGENT';

-- Source migration: v2.4.0_0727_add_a2a_agent_card_headers_and_security_fields.sql

ALTER TABLE nexent.ag_a2a_external_agent_t
    ADD COLUMN IF NOT EXISTS agent_card_headers JSONB;

COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.agent_card_headers
    IS 'Headers saved only for Agent Card discovery and refresh';

ALTER TABLE nexent.ag_a2a_external_agent_t
    ADD COLUMN IF NOT EXISTS security_schemes JSONB,
    ADD COLUMN IF NOT EXISTS security_requirements JSONB,
    ADD COLUMN IF NOT EXISTS security_credentials JSONB;

COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.security_schemes
    IS 'Security schemes declared by the Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.security_requirements
    IS 'Security requirements declared by the Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.security_credentials
    IS 'Credential values for Agent Card security schemes, never exposed by APIs';

ALTER TABLE nexent.ag_a2a_external_agent_t
    ADD COLUMN IF NOT EXISTS selected_security_requirement_index INTEGER;

COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.selected_security_requirement_index
    IS 'Selected Agent Card security requirement index used for external agent calls';

-- Source migration: v2.4.0_0803_backfill_official_skill_tool_relations.sql

-- Backfill tool dependencies for official skills installed before allowed-tools
-- metadata was added to the bundled skill archives.
SET search_path TO nexent;

WITH skill_tool_mapping(skill_name, tool_name) AS (
    VALUES
        ('analyze-image', 'analyze_image'),
        ('analyze-text-file', 'analyze_text_file'),
        ('create-file-directory', 'create_file'),
        ('create-file-directory', 'create_directory'),
        ('delete-file-directory', 'delete_file'),
        ('delete-file-directory', 'delete_directory'),
        ('email-utils', 'get_email'),
        ('email-utils', 'send_email'),
        ('list-directory', 'list_directory'),
        ('move-file-directory', 'move_item'),
        ('read-file', 'read_file'),
        ('run-shell-ssh', 'terminal'),
        ('search-datamate', 'datamate_search'),
        ('search-dify', 'dify_search'),
        ('search-idata', 'idata_search'),
        ('search-knowledge-base', 'knowledge_base_search'),
        ('search-web-exa', 'exa_search'),
        ('search-web-linkup', 'linkup_search'),
        ('search-web-tavily', 'tavily_search')
),
updated_relations AS (
    UPDATE nexent.ag_skill_tools_rel_t AS relation
    SET
        created_by = COALESCE(
            relation.created_by,
            skill.created_by,
            skill.updated_by,
            tool.created_by,
            tool.updated_by
        ),
        updated_by = COALESCE(
            relation.updated_by,
            skill.updated_by,
            skill.created_by,
            tool.updated_by,
            tool.created_by
        ),
        update_time = CURRENT_TIMESTAMP
    FROM skill_tool_mapping mapping
    JOIN nexent.ag_skill_info_t skill
        ON skill.skill_name = mapping.skill_name
        AND skill.delete_flag != 'Y'
        AND skill.source IN ('official', '官方')
    JOIN nexent.ag_tool_info_t tool
        ON tool.name = mapping.tool_name
        AND tool.delete_flag != 'Y'
        AND tool.author = skill.tenant_id
    WHERE relation.skill_id = skill.skill_id
      AND relation.tool_id = tool.tool_id
      AND relation.delete_flag != 'Y'
      AND (relation.created_by IS NULL OR relation.updated_by IS NULL)
    RETURNING relation.skill_id, relation.tool_id
)
INSERT INTO nexent.ag_skill_tools_rel_t (
    skill_id,
    tool_id,
    created_by,
    updated_by,
    delete_flag
)
SELECT
    skill.skill_id,
    tool.tool_id,
    COALESCE(skill.created_by, skill.updated_by, tool.created_by, tool.updated_by),
    COALESCE(skill.updated_by, skill.created_by, tool.updated_by, tool.created_by),
    'N'
FROM skill_tool_mapping mapping
JOIN nexent.ag_skill_info_t skill
    ON skill.skill_name = mapping.skill_name
    AND skill.delete_flag != 'Y'
    AND skill.source IN ('official', '官方')
JOIN nexent.ag_tool_info_t tool
    ON tool.name = mapping.tool_name
    AND tool.delete_flag != 'Y'
    AND tool.author = skill.tenant_id
WHERE NOT EXISTS (
    SELECT 1
    FROM nexent.ag_skill_tools_rel_t relation
    WHERE relation.skill_id = skill.skill_id
      AND relation.tool_id = tool.tool_id
      AND relation.delete_flag != 'Y'
);

-- Source migration: v2.4.0_0804_add_agent_automation_tool_idempotency.sql

-- Add idempotent source-message linkage for AgentLoop-created automation proposals.

SET search_path TO nexent;

BEGIN;

ALTER TABLE nexent.agent_automation_proposal_t
    ADD COLUMN IF NOT EXISTS source_message_id BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_automation_proposal_source_message
    ON nexent.agent_automation_proposal_t (tenant_id, user_id, source_message_id)
    WHERE delete_flag = 'N' AND source_message_id IS NOT NULL;

COMMIT;

-- Source migration: v2.5.0_0801_add_unit_invocation_id.sql

-- Persist `invocation_id` on message units so the frontend can attribute
-- model deep-thinking output to the correct sub-agent card on history replay.

SET search_path TO nexent;

ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS invocation_id VARCHAR(36);

COMMENT ON COLUMN nexent.conversation_message_unit_t.invocation_id IS
    'Identifies which sub-agent invocation produced this unit. Used by the '
    'frontend history adapter to route deep-thinking / reasoning chunks into '
    'the correct nested sub-agent card.';
