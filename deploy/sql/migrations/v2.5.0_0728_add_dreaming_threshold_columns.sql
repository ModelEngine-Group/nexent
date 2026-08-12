ALTER TABLE nexent.memory_dreaming_schedule_t
    ADD COLUMN IF NOT EXISTS min_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS min_recall_count INTEGER,
    ADD COLUMN IF NOT EXISTS min_unique_queries INTEGER;

COMMENT ON COLUMN nexent.memory_dreaming_schedule_t.min_score IS 'Per-user promotion score threshold (0-1). NULL = use system default.';
COMMENT ON COLUMN nexent.memory_dreaming_schedule_t.min_recall_count IS 'Per-user minimum recall count. NULL = use system default.';
COMMENT ON COLUMN nexent.memory_dreaming_schedule_t.min_unique_queries IS 'Per-user minimum unique query count. NULL = use system default.';
