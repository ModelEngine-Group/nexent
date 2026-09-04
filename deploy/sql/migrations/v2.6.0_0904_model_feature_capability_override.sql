-- Persist tenant-model capability and runtime-policy overrides separately from
-- the provider/catalog-derived feature capability baseline.
SET search_path TO nexent;
BEGIN;

ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS feature_capability_override JSONB DEFAULT NULL;

COMMENT ON COLUMN nexent.model_record_t.feature_capability_override IS
    'Versioned tenant-model capability and runtime-policy override without secrets.';

COMMIT;
