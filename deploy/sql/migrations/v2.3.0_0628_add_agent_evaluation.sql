-- =============================================================================
-- Agent evaluation (offline) - evaluation set & evaluation runs
-- =============================================================================
-- Version: v2.3.0
-- Date: 2026-06-30
-- Description: Add evaluation_set_t / evaluation_set_case_t / agent_evaluation_t / agent_evaluation_case_t
--
-- Note on judge_model_id:
--   Originally introduced in a follow-up migration (v2.3.0_0629_*.sql) after this
--   file had been applied in some environments. The column, its index, and column
--   comment are now defined here directly so a fresh install only needs this file.
--   Re-running this migration on an environment that already applied the original
--   0629 patch is still safe: CREATE TABLE IF NOT EXISTS is a no-op, ADD COLUMN IF
--   NOT EXISTS is a no-op, CREATE INDEX IF NOT EXISTS is a no-op, and COMMENT is
--   idempotent.
-- =============================================================================

SET search_path TO nexent;

BEGIN;

-- -----------------------------------------------------------------------------
-- Evaluation Set
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

CREATE INDEX IF NOT EXISTS ix_eval_set_tenant_id ON nexent.evaluation_set_t(tenant_id);
CREATE INDEX IF NOT EXISTS ix_eval_set_name ON nexent.evaluation_set_t(tenant_id, name);

COMMENT ON TABLE nexent.evaluation_set_t IS 'Offline evaluation sets (JSONL single-turn cases).';
COMMENT ON COLUMN nexent.evaluation_set_t.tenant_id IS 'Tenant ID for multi-tenancy isolation';
COMMENT ON COLUMN nexent.evaluation_set_t.source_filename IS 'Original uploaded filename';
COMMENT ON COLUMN nexent.evaluation_set_t.case_count IS 'Total number of cases';


-- -----------------------------------------------------------------------------
-- Evaluation Set Case
-- -----------------------------------------------------------------------------
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
CREATE INDEX IF NOT EXISTS ix_eval_set_case_tenant_id ON nexent.evaluation_set_case_t(tenant_id);

COMMENT ON TABLE nexent.evaluation_set_case_t IS 'Cases within evaluation sets.';
COMMENT ON COLUMN nexent.evaluation_set_case_t.inputs IS 'Case inputs JSON: {query: string, context?: string}';
COMMENT ON COLUMN nexent.evaluation_set_case_t.label IS 'Case label JSON: {answer: string}';


-- -----------------------------------------------------------------------------
-- Agent Evaluation Run
-- -----------------------------------------------------------------------------
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

CREATE INDEX IF NOT EXISTS ix_agent_eval_tenant_id ON nexent.agent_evaluation_t(tenant_id);
CREATE INDEX IF NOT EXISTS ix_agent_eval_agent_id ON nexent.agent_evaluation_t(tenant_id, agent_id);
CREATE INDEX IF NOT EXISTS ix_agent_eval_set_id ON nexent.agent_evaluation_t(tenant_id, evaluation_set_id);
CREATE INDEX IF NOT EXISTS ix_agent_eval_judge_model_id ON nexent.agent_evaluation_t(tenant_id, judge_model_id);

COMMENT ON TABLE nexent.agent_evaluation_t IS 'Offline evaluation runs for an agent.';
COMMENT ON COLUMN nexent.agent_evaluation_t.status IS 'Run status: PENDING/RUNNING/COMPLETED/FAILED';
COMMENT ON COLUMN nexent.agent_evaluation_t.judge_model_id IS
    'Model id used by the judge. Persisted so the background worker can recover it after restart and so the frontend can display judge_model_name.';


-- -----------------------------------------------------------------------------
-- Agent Evaluation Per-Case Result
-- -----------------------------------------------------------------------------
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
CREATE INDEX IF NOT EXISTS ix_agent_eval_case_tenant_id ON nexent.agent_evaluation_case_t(tenant_id);

COMMENT ON TABLE nexent.agent_evaluation_case_t IS 'Per-case evaluation results.';
COMMENT ON COLUMN nexent.agent_evaluation_case_t.predict IS 'Predict JSON: {answer: string, raw?: any}';
COMMENT ON COLUMN nexent.agent_evaluation_case_t.status IS 'Case status: PENDING/RUNNING/COMPLETED/FAILED';

COMMIT;
