-- P8: persist sanitized model-level reasoning and prompt-cache capabilities.
ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS feature_capability_metadata JSONB DEFAULT NULL;

COMMENT ON COLUMN nexent.model_record_t.feature_capability_metadata IS
    'Versioned reasoning and prompt-cache capability resolution without secrets.';
