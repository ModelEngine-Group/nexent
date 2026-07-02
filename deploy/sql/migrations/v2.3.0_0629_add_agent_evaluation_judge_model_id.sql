-- =============================================================================
-- Add judge_model_id to agent_evaluation_t
-- Version: v2.3.0
-- Date: 2026-06-30
-- Description:
--   Persist the judge model id on the evaluation run so that:
--     1. The frontend can display judge_model_name in the history list
--     2. The background worker can recover judge_model_id after a restart
--   Without this column, judge_model_id was only held in worker memory and
--   lost on any process restart, causing evaluations to fail permanently.
-- =============================================================================

SET search_path TO nexent;

BEGIN;

ALTER TABLE nexent.agent_evaluation_t
ADD COLUMN IF NOT EXISTS judge_model_id INTEGER;

COMMENT ON COLUMN nexent.agent_evaluation_t.judge_model_id IS
    'Model id used by the judge. Persisted so the background worker can recover it after restart and so the frontend can display judge_model_name.';

CREATE INDEX IF NOT EXISTS ix_agent_eval_judge_model_id
    ON nexent.agent_evaluation_t (tenant_id, judge_model_id);

COMMIT;
