-- Migration: Change ag_tenant_agent_t.model_id to model_ids (list of integers)
-- Date: 2026-06-17
-- Description: Migrate agent model configuration from single model_id to model_ids list
--
-- Migration strategy:
-- 1. Add new model_ids column as ARRAY(Integer)
-- 2. Migrate existing data from model_id to model_ids (wrap single value in array)
-- 3. Update column comments
-- Note: Keep model_id column for backward compatibility during transition period

SET search_path TO nexent;

BEGIN;

-- Add model_ids column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
        AND table_name = 'ag_tenant_agent_t'
        AND column_name = 'model_ids'
    ) THEN
        ALTER TABLE nexent.ag_tenant_agent_t
        ADD COLUMN model_ids INTEGER[] DEFAULT NULL;
    END IF;
END $$;

-- Migrate data from model_id to model_ids
-- Only migrate rows where model_id is not null and model_ids is null
UPDATE nexent.ag_tenant_agent_t
SET model_ids = ARRAY[model_id]
WHERE model_id IS NOT NULL
  AND (model_ids IS NULL OR array_length(model_ids, 1) IS NULL);

-- Update column comments
COMMENT ON COLUMN nexent.ag_tenant_agent_t.model_ids IS 'List of model IDs, foreign key references to model_record_t.model_id, max 5 models';

-- Add comment to model_id indicating deprecation if not already done
COMMENT ON COLUMN nexent.ag_tenant_agent_t.model_id IS '[DEPRECATED] Single model ID, use model_ids instead';

COMMIT;
