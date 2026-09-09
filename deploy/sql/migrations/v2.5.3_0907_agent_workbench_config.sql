ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS workbench_config JSONB;

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS workbench_config_version INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN nexent.conversation_record_t.workbench_config IS
    'Canonical schema-v3 Workbench conversation declaration; resolved runtime artifacts are never persisted';

COMMENT ON COLUMN nexent.conversation_record_t.workbench_config_version IS
    'Monotonic optimistic-lock version for workbench_config';
