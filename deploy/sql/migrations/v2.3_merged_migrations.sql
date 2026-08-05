-- Nexent merged SQL migrations: v2.3
-- This file is generated from historical migration files.

-- Source migration: v2.3.0_0624_add_labels_to_ag_tool_info.sql

-- Add labels column to ag_tool_info_t table for tool filtering/grouping
ALTER TABLE nexent.ag_tool_info_t
ADD COLUMN IF NOT EXISTS labels JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN nexent.ag_tool_info_t.labels IS 'JSON array of label strings for filtering/grouping tools';

-- Seed built-in labels for well-known local tools.
-- These labels serve as suggested defaults and can be modified by users.
-- Keep in sync with: backend/consts/tool_labels.py

WITH label_map AS (
    SELECT key AS tool_name, value AS label FROM jsonb_each_text('{
        "mysql_database": "database", "postgres_database": "database", "mssql_database": "database",
        "read_file": "file", "create_file": "file", "delete_file": "file",
        "create_directory": "file", "delete_directory": "file", "list_directory": "file",
        "move_item": "file",
        "tavily_search": "search", "exa_search": "search", "linkup_search": "search",
        "search_memory": "search", "knowledge_base_search": "search",
        "dify_search": "knowledge-base", "datamate_search": "knowledge-base",
        "idata_search": "knowledge-base", "haotian_search": "knowledge-base",
        "ragflow_search": "knowledge-base",
        "aidp_search": "knowledge-base",
        "analyze_image": "multimodal", "analyze_audio": "multimodal",
        "analyze_video": "multimodal", "analyze_text_file": "multimodal",
        "get_email": "email", "send_email": "email",
        "store_memory": "memory",
        "terminal": "terminal"
    }'::jsonb)
)
UPDATE nexent.ag_tool_info_t t
SET labels = to_jsonb(ARRAY[m.label])
FROM label_map m
WHERE t.name = m.tool_name AND t.labels = '[]'::jsonb;

-- Source migration: v2.3.0_0628_add_agent_evaluation_full.sql

-- =============================================================================
-- Agent evaluation (offline) - full bundle
-- =============================================================================
-- Version: v2.3.0
-- Date: 2026-06-30
-- Description: Single-file bundle for the v2.3.0 agent evaluation feature.
--   Combines what were originally three separate migration drafts (0628, 0630
--   pass_status, 0630 route grant) before any of them had been applied to
--   any environment. Use this file on fresh installs.
--
-- Idempotency: every DDL statement in this file is safe to run multiple times.
--   - CREATE TABLE IF NOT EXISTS
--   - ALTER TABLE ... ADD COLUMN IF NOT EXISTS
--   - CREATE INDEX IF NOT EXISTS
--   - COMMENT ON (overwrites previous value, no-op if identical)
--   - INSERT ... ON CONFLICT (role_permission_id) DO NOTHING
--
-- Sections:
--   1. evaluation_set_t / evaluation_set_case_t / agent_evaluation_t /
--      agent_evaluation_case_t (incl. judge_model_id on agent_evaluation_t)
--   2. pass_status column on agent_evaluation_case_t + composite index
--   3. LEFT_NAV_MENU '/space' grant for roles that have /agent-space
--
-- Design decisions (see PR review 2026-06-30):
--   * No standalone (tenant_id) index on any table. Every case-level and
--     run-level read is scoped by PK or by a foreign key into a parent that
--     itself is already tenant-scoped at the application layer. A bare
--     (tenant_id) index has no real query plan and only inflates write cost.
--   * No (tenant_id, judge_model_id) index. judge_model_id is read alongside
--     the row via PK; "list runs by judge model" is not a supported query.
--   * No (tenant_id, evaluation_set_id) on evaluation_set_case_t. The set
--     itself is tenant-scoped at the app layer, and the existing
--     (evaluation_set_id) index already covers set-case listing.
--   * ix_agent_eval_case_pass_status is (agent_evaluation_id, pass_status)
--     rather than (tenant_id, agent_evaluation_id, pass_status): case-level
--     reads never filter on tenant_id directly, and dropping the leading
--     tenant_id column keeps the most common "list failed cases for run X"
--     query on a single composite index.
--   * Section 3 INSERT must include parent_key (see 0622 menu migration) so
--     a future renderer that joins on parent_key does not leave this batch
--     as orphans. /space is a first-level entry for the route guard only,
--     so parent_key is NULL.
-- =============================================================================

SET search_path TO nexent;

BEGIN;


-- -----------------------------------------------------------------------------
-- Section 1: Evaluation set & evaluation run tables
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nexent.evaluation_set_t (
    evaluation_set_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,

    name VARCHAR(255) NOT NULL,
    description TEXT,

    source_filename VARCHAR(255),
    case_count INTEGER DEFAULT 0,

    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS ix_eval_set_name ON nexent.evaluation_set_t(tenant_id, name);

COMMENT ON TABLE nexent.evaluation_set_t IS 'Offline evaluation sets (JSONL single-turn cases).';
COMMENT ON COLUMN nexent.evaluation_set_t.tenant_id IS 'Tenant ID for multi-tenancy isolation';
COMMENT ON COLUMN nexent.evaluation_set_t.source_filename IS 'Original uploaded filename';
COMMENT ON COLUMN nexent.evaluation_set_t.case_count IS 'Total number of cases';


CREATE TABLE IF NOT EXISTS nexent.evaluation_set_case_t (
    evaluation_set_case_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    evaluation_set_id BIGINT NOT NULL,

    case_id VARCHAR(128),
    inputs JSONB NOT NULL,
    label JSONB NOT NULL,
    order_no INTEGER DEFAULT 0,

    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS ix_eval_set_case_set_id ON nexent.evaluation_set_case_t(evaluation_set_id);

COMMENT ON TABLE nexent.evaluation_set_case_t IS 'Cases within evaluation sets.';
COMMENT ON COLUMN nexent.evaluation_set_case_t.inputs IS 'Case inputs JSON: {query: string, context?: string}';
COMMENT ON COLUMN nexent.evaluation_set_case_t.label IS 'Case label JSON: {answer: string}';


CREATE TABLE IF NOT EXISTS nexent.agent_evaluation_t (
    agent_evaluation_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,

    agent_id INTEGER NOT NULL,
    agent_version_no INTEGER NOT NULL,

    evaluation_set_id BIGINT NOT NULL,

    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',

    progress_total INTEGER DEFAULT 0,
    progress_done INTEGER DEFAULT 0,

    score_overall DOUBLE PRECISION,
    error_message TEXT,

    judge_model_id INTEGER,

    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS ix_agent_eval_agent_id ON nexent.agent_evaluation_t(tenant_id, agent_id);
CREATE INDEX IF NOT EXISTS ix_agent_eval_set_id ON nexent.agent_evaluation_t(tenant_id, evaluation_set_id);

COMMENT ON TABLE nexent.agent_evaluation_t IS 'Offline evaluation runs for an agent.';
COMMENT ON COLUMN nexent.agent_evaluation_t.status IS 'Run status: PENDING/RUNNING/COMPLETED/FAILED';
COMMENT ON COLUMN nexent.agent_evaluation_t.judge_model_id IS
    'Model id used by the judge. Persisted so the background worker can recover it after restart and so the frontend can display judge_model_name.';


CREATE TABLE IF NOT EXISTS nexent.agent_evaluation_case_t (
    agent_evaluation_case_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,

    agent_evaluation_id BIGINT NOT NULL,
    evaluation_set_case_id BIGINT NOT NULL,

    inputs JSONB NOT NULL,
    label JSONB NOT NULL,
    predict JSONB,

    score DOUBLE PRECISION,
    reason TEXT,

    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    error_message TEXT,

    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS ix_agent_eval_case_eval_id ON nexent.agent_evaluation_case_t(agent_evaluation_id);

COMMENT ON TABLE nexent.agent_evaluation_case_t IS 'Per-case evaluation results.';
COMMENT ON COLUMN nexent.agent_evaluation_case_t.predict IS 'Predict JSON: {answer: string, raw?: any}';
COMMENT ON COLUMN nexent.agent_evaluation_case_t.status IS 'Case status: PENDING/RUNNING/COMPLETED/FAILED';


-- -----------------------------------------------------------------------------
-- Section 2: pass_status on agent_evaluation_case_t
-- -----------------------------------------------------------------------------
-- Stores the binary judge result ("pass" / "fail") for each case.
-- Enables fast filtering for failed-case reports and storage optimization:
--   passed cases have predict/reason/label.answer cleared to save space,
--   while only failed cases retain full detail.

ALTER TABLE nexent.agent_evaluation_case_t
ADD COLUMN IF NOT EXISTS pass_status VARCHAR(16);

COMMENT ON COLUMN nexent.agent_evaluation_case_t.pass_status IS
    'Judge result per case: pass / fail. pass cases have predict/reason/label.answer cleared to save space.';

-- Composite index to support failed-case listing and "only failed" reports.
-- Scoped by (agent_evaluation_id, pass_status) only; tenant_id is enforced
-- at the application layer via the parent run's tenant.
CREATE INDEX IF NOT EXISTS ix_agent_eval_case_pass_status
    ON nexent.agent_evaluation_case_t (agent_evaluation_id, pass_status);


-- -----------------------------------------------------------------------------
-- Section 3: Grant /space LEFT_NAV_MENU so the evaluation page is reachable
-- -----------------------------------------------------------------------------
-- The agent evaluation page lives at the route prefix /space/agents/{id}/evaluate.
-- The previous menu migration (v2.2.2_0622_update_left_nav_menu.sql) removed
-- the legacy /space entry when it refactored the menu structure. As a result
-- the frontend route guard (which uses accessibleRoutes prefix matching) blocks
-- any user from entering the evaluation page with "no access permission".
--
-- This section adds LEFT_NAV_MENU = '/space' for every role that already has
-- access to the resource-space (i.e. /agent-space). This entry is NOT rendered
-- in the side navigation (SideNavigation uses exact-match against ROUTE_CONFIG)
-- but it IS picked up by the backend as part of accessibleRoutes, so the route
-- guard will allow /space/agents/{id}/evaluate and its sub-paths.

-- Roles that already have /resource-space (and thus /agent-space) get /space.
-- Mirrors v2.2.2_0622_update_left_nav_menu.sql IDs (16xx range) to keep the
-- scheme consistent. parent_key is NULL: /space is a top-level entry used
-- only by the backend route guard (prefix match on accessibleRoutes) and
-- is not rendered by SideNavigation.
INSERT INTO nexent.role_permission_t
    (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key)
VALUES
    (1600, 'SU',          'VISIBILITY', 'LEFT_NAV_MENU', '/space', NULL),
    (1601, 'ADMIN',       'VISIBILITY', 'LEFT_NAV_MENU', '/space', NULL),
    (1602, 'DEV',         'VISIBILITY', 'LEFT_NAV_MENU', '/space', NULL),
    (1603, 'SPEED',       'VISIBILITY', 'LEFT_NAV_MENU', '/space', NULL),
    (1604, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/space', NULL)
ON CONFLICT (role_permission_id) DO NOTHING;


COMMIT;

-- Source migration: v2.3.0_0629_add_skill_repository_table.sql

-- Migration: Add ag_skill_repository_t table
-- Date: 2026-06-29
-- Description: Skill marketplace repository for frozen installable skill snapshots.

SET search_path TO nexent;

CREATE SEQUENCE IF NOT EXISTS nexent.ag_skill_repository_t_skill_repository_id_seq;

CREATE TABLE IF NOT EXISTS nexent.ag_skill_repository_t (
    skill_repository_id BIGINT NOT NULL DEFAULT nextval('nexent.ag_skill_repository_t_skill_repository_id_seq'),
    publisher_tenant_id VARCHAR(100) NOT NULL,
    publisher_user_id VARCHAR(100) NOT NULL,
    skill_id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    source VARCHAR(30),
    submitted_by VARCHAR(100),
    category_id INTEGER,
    tags TEXT[],
    icon VARCHAR(100),
    downloads INTEGER DEFAULT 0,
    skill_info_json JSONB NOT NULL,
    skill_zip_base64 TEXT NOT NULL,
    status VARCHAR(30) DEFAULT 'not_shared',
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT ag_skill_repository_t_pkey PRIMARY KEY (skill_repository_id)
);

ALTER SEQUENCE nexent.ag_skill_repository_t_skill_repository_id_seq
    OWNED BY nexent.ag_skill_repository_t.skill_repository_id;

ALTER TABLE nexent.ag_skill_repository_t OWNER TO root;

ALTER TABLE nexent.ag_skill_repository_t
  ADD COLUMN IF NOT EXISTS submitted_by VARCHAR(100),
  ADD COLUMN IF NOT EXISTS icon VARCHAR(100),
  ADD COLUMN IF NOT EXISTS downloads INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS skill_zip_base64 TEXT;

COMMENT ON TABLE nexent.ag_skill_repository_t IS 'Skill marketplace repository for frozen installable skill snapshots';
COMMENT ON COLUMN nexent.ag_skill_repository_t.skill_repository_id IS 'Skill repository listing ID, unique primary key';
COMMENT ON COLUMN nexent.ag_skill_repository_t.publisher_tenant_id IS 'Publisher tenant ID';
COMMENT ON COLUMN nexent.ag_skill_repository_t.publisher_user_id IS 'Publisher user ID';
COMMENT ON COLUMN nexent.ag_skill_repository_t.skill_id IS 'Source skill ID from ag_skill_info_t; unique when active (delete_flag = N)';
COMMENT ON COLUMN nexent.ag_skill_repository_t.name IS 'Skill name for display and search';
COMMENT ON COLUMN nexent.ag_skill_repository_t.description IS 'Skill description';
COMMENT ON COLUMN nexent.ag_skill_repository_t.source IS 'Skill source';
COMMENT ON COLUMN nexent.ag_skill_repository_t.submitted_by IS 'Submitter email when listing enters pending_review';
COMMENT ON COLUMN nexent.ag_skill_repository_t.category_id IS 'Optional marketplace category ID';
COMMENT ON COLUMN nexent.ag_skill_repository_t.tags IS 'Marketplace tags';
COMMENT ON COLUMN nexent.ag_skill_repository_t.icon IS 'Marketplace card icon (emoji or URL)';
COMMENT ON COLUMN nexent.ag_skill_repository_t.downloads IS 'Marketplace install count for card display';
COMMENT ON COLUMN nexent.ag_skill_repository_t.skill_info_json IS 'Frozen skill metadata snapshot';
COMMENT ON COLUMN nexent.ag_skill_repository_t.skill_zip_base64 IS 'Frozen skill ZIP payload encoded as base64';
COMMENT ON COLUMN nexent.ag_skill_repository_t.status IS 'Listing status: not_shared / pending_review / rejected / shared';
COMMENT ON COLUMN nexent.ag_skill_repository_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_skill_repository_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_skill_repository_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.ag_skill_repository_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.ag_skill_repository_t.delete_flag IS 'Soft delete flag: Y/N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_repository_skill_active
    ON nexent.ag_skill_repository_t (skill_id)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_skill_repository_publisher_delete
    ON nexent.ag_skill_repository_t (publisher_tenant_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_skill_repository_status_delete
    ON nexent.ag_skill_repository_t (status, delete_flag);

CREATE INDEX IF NOT EXISTS idx_skill_repository_name_delete
    ON nexent.ag_skill_repository_t (name, delete_flag);

CREATE INDEX IF NOT EXISTS idx_skill_repository_tags_gin
    ON nexent.ag_skill_repository_t USING GIN (tags);

CREATE OR REPLACE FUNCTION update_ag_skill_repository_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_ag_skill_repository_update_time() IS 'Auto-update update_time for ag_skill_repository_t';

DROP TRIGGER IF EXISTS update_ag_skill_repository_update_time_trigger ON nexent.ag_skill_repository_t;
CREATE TRIGGER update_ag_skill_repository_update_time_trigger
BEFORE UPDATE ON nexent.ag_skill_repository_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_skill_repository_update_time();

COMMENT ON TRIGGER update_ag_skill_repository_update_time_trigger
ON nexent.ag_skill_repository_t IS 'Trigger to maintain update_time';

-- Source migration: v2.3.0_0703_history_projection_fields.sql

-- Migration: Add step_index for ReAct step tracking
-- Date: 2026-07-03 (revised 2026-07-09)
-- Description: Add step_index column to conversation_message_unit_t.
-- Drops previously added run_id, tool_call_id, event_time columns
-- that are no longer needed after review.

SET search_path TO nexent;
BEGIN;

-- Add step_index (renamed from step_id)
ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS step_index INTEGER DEFAULT NULL;

COMMENT ON COLUMN nexent.conversation_message_unit_t.step_index IS
    'ReAct step sequence number within this message. Increments on step_count chunks.';

-- Drop columns from previous revision (idempotent)
ALTER TABLE nexent.conversation_message_unit_t
    DROP COLUMN IF EXISTS run_id;
ALTER TABLE nexent.conversation_message_unit_t
    DROP COLUMN IF EXISTS step_id;
ALTER TABLE nexent.conversation_message_unit_t
    DROP COLUMN IF EXISTS tool_call_id;
ALTER TABLE nexent.conversation_message_unit_t
    DROP COLUMN IF EXISTS event_time;
ALTER TABLE nexent.conversation_message_t
    DROP COLUMN IF EXISTS run_id;

-- Drop obsolete indexes
DROP INDEX IF EXISTS nexent.idx_message_unit_conversation_run;
DROP INDEX IF EXISTS nexent.idx_message_unit_tool_call;

-- New index for step-based queries
CREATE INDEX IF NOT EXISTS idx_message_unit_message_step
    ON nexent.conversation_message_unit_t (message_id, step_index);

COMMIT;

-- Source migration: v2.3.0_0709_add_conversation_agent_id.sql

-- Store the latest agent used by each conversation so history selection can restore agent context.
ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS agent_id INTEGER;

COMMENT ON COLUMN nexent.conversation_record_t.agent_id
    IS 'Agent ID used by the latest run in this conversation';

-- Source migration: v2.3.0_0709_add_mcp_market_tables.sql

-- Migration: Add MCP market tables (v2.4.0 single-table design)
-- Date: 2026-07-09
-- Description: Create mcp_market_record_t (single-table with inline review status),
--              add market_id to mcp_record_t, add review_status/review_type to
--              mcp_community_record_t.

SET search_path TO nexent;

BEGIN;

-- ============================================================================
-- 1) Extend mcp_record_t for market integration (idempotent)
-- ============================================================================
ALTER TABLE IF EXISTS nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS market_id INTEGER;

COMMENT ON COLUMN nexent.mcp_record_t.market_id IS 'Published market record ID (FK to mcp_market_record_t)';

-- ============================================================================
-- 2) Extend mcp_community_record_t for review workflow (idempotent)
-- ============================================================================
ALTER TABLE IF EXISTS nexent.mcp_community_record_t
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(30) DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS review_type VARCHAR(30) DEFAULT 'initial_listing';

COMMENT ON COLUMN nexent.mcp_community_record_t.review_status IS 'Review status: pending/approved/rejected/offline';
COMMENT ON COLUMN nexent.mcp_community_record_t.review_type IS 'Review submission type: initial_listing/update';

-- ============================================================================
-- 3) Create mcp_market_record_t (single-table design)
-- ============================================================================

CREATE SEQUENCE IF NOT EXISTS nexent.mcp_market_record_t_market_id_seq;

CREATE TABLE IF NOT EXISTS nexent.mcp_market_record_t (
    market_id       BIGINT NOT NULL DEFAULT nextval('nexent.mcp_market_record_t_market_id_seq'),
    tenant_id       VARCHAR(100) NOT NULL,
    user_id         VARCHAR(100) NOT NULL,
    mcp_name        VARCHAR(100) NOT NULL,
    mcp_server      VARCHAR(500) NOT NULL,
    source          VARCHAR(30) DEFAULT 'community',
    registry_json   JSONB,
    transport_type  VARCHAR(30),
    config_json     JSON,
    tags            TEXT[],
    description     TEXT,
    download_count  INTEGER DEFAULT 0,
    review_status   VARCHAR(30) DEFAULT 'not_shared',
    submitted_by    VARCHAR(100),
    source_mcp_id   INTEGER,
    create_time     TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time     TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by      VARCHAR(100),
    updated_by      VARCHAR(100),
    delete_flag     VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.mcp_market_record_t OWNER TO root;

COMMENT ON TABLE nexent.mcp_market_record_t IS 'MCP market (community) records — single table covering all listing states';
COMMENT ON COLUMN nexent.mcp_market_record_t.market_id IS 'Market record ID, unique primary key';
COMMENT ON COLUMN nexent.mcp_market_record_t.tenant_id IS 'Publisher tenant ID';
COMMENT ON COLUMN nexent.mcp_market_record_t.user_id IS 'Publisher user ID';
COMMENT ON COLUMN nexent.mcp_market_record_t.mcp_name IS 'MCP name';
COMMENT ON COLUMN nexent.mcp_market_record_t.mcp_server IS 'MCP server URL';
COMMENT ON COLUMN nexent.mcp_market_record_t.source IS 'Source type, fixed to community';
COMMENT ON COLUMN nexent.mcp_market_record_t.registry_json IS 'Full MCP metadata JSON';
COMMENT ON COLUMN nexent.mcp_market_record_t.transport_type IS 'Transport type: http/sse/container';
COMMENT ON COLUMN nexent.mcp_market_record_t.config_json IS 'Public-shareable MCP configuration JSON';
COMMENT ON COLUMN nexent.mcp_market_record_t.tags IS 'Tags';
COMMENT ON COLUMN nexent.mcp_market_record_t.description IS 'Description';
COMMENT ON COLUMN nexent.mcp_market_record_t.download_count IS 'Cumulative download/install count';
COMMENT ON COLUMN nexent.mcp_market_record_t.review_status IS 'Listing status: not_shared/pending_review/shared/rejected';
COMMENT ON COLUMN nexent.mcp_market_record_t.submitted_by IS 'Email of the user who submitted for review';
COMMENT ON COLUMN nexent.mcp_market_record_t.source_mcp_id IS 'Source mcp_record_t ID that was published to the market';

-- Indexes
CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_market_name_active
    ON nexent.mcp_market_record_t (mcp_name)
    WHERE delete_flag = 'N' AND review_status = 'shared';

CREATE INDEX IF NOT EXISTS idx_mcp_market_tenant_delete
    ON nexent.mcp_market_record_t (tenant_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_market_status_delete
    ON nexent.mcp_market_record_t (review_status, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_market_tags_gin
    ON nexent.mcp_market_record_t USING GIN (tags);

-- Trigger: auto-update update_time
CREATE OR REPLACE FUNCTION update_mcp_market_record_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_mcp_market_record_update_time() IS 'Auto-update update_time for mcp_market_record_t';

DROP TRIGGER IF EXISTS update_mcp_market_record_update_time_trigger ON nexent.mcp_market_record_t;
CREATE TRIGGER update_mcp_market_record_update_time_trigger
BEFORE UPDATE ON nexent.mcp_market_record_t
FOR EACH ROW
EXECUTE FUNCTION update_mcp_market_record_update_time();

COMMENT ON TRIGGER update_mcp_market_record_update_time_trigger ON nexent.mcp_market_record_t IS 'Trigger to maintain update_time';

ALTER SEQUENCE nexent.mcp_market_record_t_market_id_seq OWNED BY nexent.mcp_market_record_t.market_id;

-- ============================================================================
-- 4) Backfill: migrate old community records to the market table
--    Old mcp_community_record_t had no review workflow — published immediately.
--    Set their review_status to approved, copy to mcp_market_record_t as 'shared',
--    then link mcp_record_t rows to the newly created market records.
-- ============================================================================

-- Mark old community records as approved (they were published without review)
UPDATE nexent.mcp_community_record_t
SET review_status = 'approved'
WHERE (review_status IS NULL OR review_status = 'pending')
  AND delete_flag != 'Y';

-- Backfill: copy old community records into the market table (idempotent)
WITH inserted AS (
    INSERT INTO nexent.mcp_market_record_t (
        tenant_id, user_id, mcp_name, mcp_server, source,
        registry_json, transport_type, config_json, tags, description,
        download_count, create_time, update_time, created_by, updated_by, delete_flag,
        review_status
    )
    SELECT
        c.tenant_id, c.user_id, c.mcp_name, c.mcp_server, c.source,
        c.registry_json, c.transport_type, c.config_json, c.tags, c.description,
        0, c.create_time, c.update_time, c.created_by, c.updated_by, c.delete_flag,
        'shared'
    FROM nexent.mcp_community_record_t c
    WHERE c.delete_flag != 'Y'
      AND c.review_status = 'approved'
      AND NOT EXISTS (
          SELECT 1 FROM nexent.mcp_market_record_t m
          WHERE m.tenant_id = c.tenant_id
            AND m.mcp_name = c.mcp_name
      )
    RETURNING market_id, tenant_id, mcp_name
)
UPDATE nexent.mcp_record_t AS mr
SET market_id = ins.market_id
FROM inserted AS ins
WHERE mr.tenant_id = ins.tenant_id
  AND mr.mcp_name = ins.mcp_name
  AND mr.market_id IS NULL;

COMMIT;

-- Source migration: v2.3.0_0713_move_owner_manage_to_su.sql

-- ============================================================
-- Move /owner-manage left-nav from ASSET_OWNER to SU
-- Migration Date: 2026-07-13
-- ============================================================
-- ASSET_OWNER no longer sees the asset-admin resource management page.
-- SU gains /owner-manage (id 1003) alongside existing / and /resource-manage.
-- ============================================================

BEGIN;

-- Remove ASSET_OWNER access to /owner-manage
DELETE FROM nexent.role_permission_t
WHERE role_permission_id = 1505
   OR (
        user_role = 'ASSET_OWNER'
        AND permission_category = 'VISIBILITY'
        AND permission_type = 'LEFT_NAV_MENU'
        AND permission_subtype = '/owner-manage'
    );

-- Grant SU access to /owner-manage (idempotent)
DELETE FROM nexent.role_permission_t
WHERE role_permission_id = 1003
   OR (
        user_role = 'SU'
        AND permission_category = 'VISIBILITY'
        AND permission_type = 'LEFT_NAV_MENU'
        AND permission_subtype = '/owner-manage'
    );

INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
) VALUES (
    1003,
    'SU',
    'VISIBILITY',
    'LEFT_NAV_MENU',
    '/owner-manage'
);

COMMIT;

-- Source migration: v2.3.0_0718_add_agent_context_policy.sql

-- Add the agent-level context processing mode override.
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS context_policy JSONB;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.context_policy IS
'Agent-level context processing override (passthrough/adaptive_compact); NULL preserves the platform default';

-- Source migration: v2.3.1_0717_add_notification_tables.sql

-- Migration: Add notification_t and notification_receiver_t tables
-- Date: 2026-07-17
-- Description: In-app notification message table plus per-user fan-out delivery/read table.

SET search_path TO nexent;

-- notification_t: one row per message
CREATE SEQUENCE IF NOT EXISTS nexent.notification_t_notification_id_seq;

CREATE TABLE IF NOT EXISTS nexent.notification_t (
    notification_id BIGINT NOT NULL DEFAULT nextval('nexent.notification_t_notification_id_seq'),
    event_type VARCHAR(50) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    unique_id BIGINT,
    details JSONB,
    scope VARCHAR(20) NOT NULL,
    tenant_id VARCHAR(100),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT notification_t_pkey PRIMARY KEY (notification_id)
);

ALTER SEQUENCE nexent.notification_t_notification_id_seq
    OWNED BY nexent.notification_t.notification_id;
ALTER TABLE nexent.notification_t OWNER TO root;

COMMENT ON TABLE nexent.notification_t IS 'In-app notification message table; per-user delivery lives in notification_receiver_t';
COMMENT ON COLUMN nexent.notification_t.notification_id IS 'Notification ID, unique primary key';
COMMENT ON COLUMN nexent.notification_t.event_type IS 'Event type, e.g. repository_review_approved / repository_review_rejected';
COMMENT ON COLUMN nexent.notification_t.resource_type IS 'Resource type, e.g. agent_repository / skill_repository / mcp_repository';
COMMENT ON COLUMN nexent.notification_t.unique_id IS 'Related resource primary key (e.g. agent_repository_id)';
COMMENT ON COLUMN nexent.notification_t.details IS 'i18n interpolation details for the event template';
COMMENT ON COLUMN nexent.notification_t.scope IS 'Audience scope: SU / TENANT / TENANT_ADMIN / TENANT_USER / USER';
COMMENT ON COLUMN nexent.notification_t.tenant_id IS 'Target tenant; NULL for SU scope';
COMMENT ON COLUMN nexent.notification_t.is_active IS 'Whether this notification is still active/valid';
COMMENT ON COLUMN nexent.notification_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.notification_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.notification_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.notification_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.notification_t.delete_flag IS 'Soft delete flag: Y/N';

CREATE INDEX IF NOT EXISTS ix_notification_event_resource_unique_active
    ON nexent.notification_t (event_type, resource_type, unique_id, is_active);

-- notification_receiver_t: one row per receiver (fan-out)
CREATE SEQUENCE IF NOT EXISTS nexent.notification_receiver_t_receiver_id_seq;

CREATE TABLE IF NOT EXISTS nexent.notification_receiver_t (
    receiver_id BIGINT NOT NULL DEFAULT nextval('nexent.notification_receiver_t_receiver_id_seq'),
    notification_id BIGINT NOT NULL,
    receiver_user_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100),
    is_read BOOLEAN DEFAULT FALSE,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT notification_receiver_t_pkey PRIMARY KEY (receiver_id)
);

ALTER SEQUENCE nexent.notification_receiver_t_receiver_id_seq
    OWNED BY nexent.notification_receiver_t.receiver_id;
ALTER TABLE nexent.notification_receiver_t OWNER TO root;

COMMENT ON TABLE nexent.notification_receiver_t IS 'Per-user notification delivery and read status (fan-out from notification_t)';
COMMENT ON COLUMN nexent.notification_receiver_t.receiver_id IS 'Receiver row ID, unique primary key';
COMMENT ON COLUMN nexent.notification_receiver_t.notification_id IS 'FK to notification_t.notification_id';
COMMENT ON COLUMN nexent.notification_receiver_t.receiver_user_id IS 'Receiver user ID';
COMMENT ON COLUMN nexent.notification_receiver_t.tenant_id IS 'Tenant ID for multi-tenancy isolation';
COMMENT ON COLUMN nexent.notification_receiver_t.is_read IS 'Whether this receiver has read the notification';
COMMENT ON COLUMN nexent.notification_receiver_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.notification_receiver_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.notification_receiver_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.notification_receiver_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.notification_receiver_t.delete_flag IS 'Soft delete flag: Y/N';

CREATE INDEX IF NOT EXISTS ix_notification_receiver_user_read
    ON nexent.notification_receiver_t (receiver_user_id, is_read);
CREATE INDEX IF NOT EXISTS ix_notification_receiver_notification_id
    ON nexent.notification_receiver_t (notification_id);

-- update_time triggers
CREATE OR REPLACE FUNCTION update_notification_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_notification_update_time_trigger ON nexent.notification_t;
CREATE TRIGGER update_notification_update_time_trigger
BEFORE UPDATE ON nexent.notification_t
FOR EACH ROW
EXECUTE FUNCTION update_notification_update_time();

CREATE OR REPLACE FUNCTION update_notification_receiver_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_notification_receiver_update_time_trigger ON nexent.notification_receiver_t;
CREATE TRIGGER update_notification_receiver_update_time_trigger
BEFORE UPDATE ON nexent.notification_receiver_t
FOR EACH ROW
EXECUTE FUNCTION update_notification_receiver_update_time();

ALTER TABLE nexent.ag_agent_repository_t
    ADD COLUMN IF NOT EXISTS content TEXT;

COMMENT ON COLUMN nexent.ag_agent_repository_t.content IS
    'Listing note on submit or review opinion on approve/reject';

ALTER TABLE nexent.ag_agent_repository_t
    ADD COLUMN IF NOT EXISTS content TEXT;

COMMENT ON COLUMN nexent.ag_agent_repository_t.content IS
    'Listing note on submit or review opinion on approve/reject';

ALTER TABLE nexent.ag_skill_repository_t
    ADD COLUMN IF NOT EXISTS content TEXT;

COMMENT ON COLUMN nexent.ag_skill_repository_t.content IS
    'Listing note on submit or review opinion on approve/reject';

ALTER TABLE nexent.mcp_market_record_t
    ADD COLUMN IF NOT EXISTS content TEXT;

COMMENT ON COLUMN nexent.mcp_market_record_t.content IS
    'Listing note on submit or review opinion on approve/reject';
