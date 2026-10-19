-- Migration kind: REQUIRED_SCHEMA
-- Required for: management-side trusted model snapshots consumed by optional Agent Cores.
-- This transitional envelope is decoded by the canonical ModelService storage codec.
ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS runtime_outlet_snapshot JSONB;

COMMENT ON COLUMN nexent.model_record_t.runtime_outlet_snapshot IS
    'Management-owned canonical outlet row plus source fingerprint; NULL requires explicit provisioning. Contains no credentials; shared profile codec validates the complete envelope, maximum 1 MiB.';

-- Backfill is explicit and application-owned: no SQL inference of capabilities.
-- Run backend/scripts/migrate_runtime_outlets.py after applying this migration.
