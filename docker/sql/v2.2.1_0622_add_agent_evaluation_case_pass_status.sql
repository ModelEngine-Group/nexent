-- Migration: Add pass_status column to agent_evaluation_case_t
-- Description: Stores the binary judge result ("pass" / "fail") for each case.
--              This enables fast filtering for failed-case reports and storage
--              optimization: passed cases have predict/reason/label.answer cleared
--              to save space, while only failed cases retain full detail.

ALTER TABLE nexent.agent_evaluation_case_t
ADD COLUMN IF NOT EXISTS pass_status VARCHAR(16);

COMMENT ON COLUMN nexent.agent_evaluation_case_t.pass_status IS
    'Judge result per case: pass / fail. pass cases have predict/reason/label.answer cleared to save space.';

-- Composite index to support failed-case listing and "only failed" reports
CREATE INDEX IF NOT EXISTS ix_agent_eval_case_pass_status
    ON nexent.agent_evaluation_case_t (tenant_id, agent_evaluation_id, pass_status);
