-- =============================================================================
-- Knowledge Record Timestamps — V4 standard spec compliance
-- =============================================================================
-- Version: v2.3.0
-- Date: 2026-07-10
-- Description: Add create_time / update_time columns to knowledge_record_t table
--   so that the V4 standard API can surface ISO-8601 created_at / updated_at
--   timestamps in create/list/get responses.
--
-- Idempotency: every DDL statement is safe to run multiple times.
-- =============================================================================

-- Add create_time / update_time columns if they do not already exist
ALTER TABLE nexent.knowledge_record_t
    ADD COLUMN IF NOT EXISTS create_time TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS update_time TIMESTAMP NOT NULL DEFAULT NOW();

-- Auto-update update_time on every row change
CREATE OR REPLACE FUNCTION nexent.update_knowledge_record_update_time()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.update_time := NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_knowledge_record_update_time ON nexent.knowledge_record_t;
CREATE TRIGGER trg_knowledge_record_update_time
    BEFORE UPDATE ON nexent.knowledge_record_t
    FOR EACH ROW EXECUTE FUNCTION nexent.update_knowledge_record_update_time();
