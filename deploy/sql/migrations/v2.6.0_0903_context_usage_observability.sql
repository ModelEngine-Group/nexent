-- Persist content-free request-budget, compaction, overflow, and usage evidence.
SET search_path TO nexent;
BEGIN;

ALTER TABLE nexent.model_monitoring_record_t
    ADD COLUMN IF NOT EXISTS context_budget_evidence JSONB DEFAULT NULL;

COMMENT ON COLUMN nexent.model_monitoring_record_t.context_budget_evidence IS
    'Content-free request-budget, compaction, overflow, recovery, and usage evidence.';

COMMIT;
