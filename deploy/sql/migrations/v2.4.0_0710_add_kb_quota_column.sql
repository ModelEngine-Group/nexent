-- Add quota_limit_bytes column to knowledge_record_t for per-KB soft storage quota
-- NULL = unlimited (shares tenant pool freely)

ALTER TABLE nexent.knowledge_record_t ADD COLUMN IF NOT EXISTS quota_limit_bytes BIGINT;
