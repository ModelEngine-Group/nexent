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
