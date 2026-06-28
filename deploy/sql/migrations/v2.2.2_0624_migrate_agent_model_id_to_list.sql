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