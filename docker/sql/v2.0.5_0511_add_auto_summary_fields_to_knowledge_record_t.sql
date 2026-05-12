-- Migration: Add auto-summary fields to knowledge_record_t table
-- Date: 2026-05-11
-- Description: Add summary_frequency, last_summary_time, and last_doc_update_time fields for auto-summary feature
-- This SQL consolidates fields added in multiple commits for clean upgrade path

-- Add summary_frequency column (auto-summary frequency configuration)
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS summary_frequency VARCHAR(10);

-- Add last_summary_time column (timestamp of last summary generation)
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS last_summary_time TIMESTAMP;

-- Add last_doc_update_time column (timestamp of last document add/delete operation)
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS last_doc_update_time TIMESTAMP;

-- Add comments to the columns
COMMENT ON COLUMN nexent.knowledge_record_t.summary_frequency IS 'Auto-summary frequency: 1h, 3h, 6h, 1d, 1w, or NULL (disabled)';
COMMENT ON COLUMN nexent.knowledge_record_t.last_summary_time IS 'Timestamp of last summary generation';
COMMENT ON COLUMN nexent.knowledge_record_t.last_doc_update_time IS 'Timestamp of last document add/delete operation, used for auto-summary optimization to skip unnecessary summary regeneration';