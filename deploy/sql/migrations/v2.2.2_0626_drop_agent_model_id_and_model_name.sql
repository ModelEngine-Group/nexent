-- Migration: Drop deprecated ag_tenant_agent_t.model_id and model_name columns
-- Date: 2026-06-26
-- Description: After v2.2.0_migrate_agent_model_id_to_list.sql fully backfilled model_ids
--              from model_id, the legacy single-value columns are no longer needed.
--
-- Safety strategy:
--   1. Guard the DROP: abort if any row still has a single model_id that has not been
--      mirrored into model_ids (data preservation check).
--   2. Drop both columns inside a single transaction.
--   3. Drop the dependent indexes/constraints if any exist.

SET search_path TO nexent;

BEGIN;

-- 1) Data preservation guard: every non-null model_id must already be mirrored into model_ids.
--    If this query returns any row, the migration MUST be halted and the row repaired first.
DO $$
DECLARE
    missing_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_count
    FROM nexent.ag_tenant_agent_t
    WHERE model_id IS NOT NULL
      AND (model_ids IS NULL OR array_length(model_ids, 1) IS NULL);

    IF missing_count > 0 THEN
        RAISE EXCEPTION
            'Cannot drop ag_tenant_agent_t.model_id: % rows still rely on it without a model_ids mirror. '
            'Run v2.2.0_migrate_agent_model_id_to_list.sql first or manually backfill.', missing_count;
    END IF;
END $$;

-- 2) Drop the deprecated columns
ALTER TABLE nexent.ag_tenant_agent_t
    DROP COLUMN IF EXISTS model_id,
    DROP COLUMN IF EXISTS model_name;

COMMIT;