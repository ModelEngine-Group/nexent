-- Add model_type column to model_monitoring_record_t
-- Classifies monitoring records by model type (llm, embedding, multi_embedding, etc.)
-- Run this script against the 'nexent' schema in PostgreSQL.

ALTER TABLE nexent.model_monitoring_record_t
    ADD COLUMN IF NOT EXISTS model_type VARCHAR(20) DEFAULT 'llm';

-- Index for filtering/grouping by model type
CREATE INDEX IF NOT EXISTS ix_monitoring_model_type
    ON nexent.model_monitoring_record_t (model_type);
