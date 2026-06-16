-- W1: Persist resolved model capacity snapshot fields on monitoring records.
-- All columns are nullable and additive so existing monitoring rows remain valid.

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS context_window_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS default_output_reserve_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS capability_profile_version VARCHAR(100) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS capacity_source VARCHAR(100) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS requested_output_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS provider_input_limit_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS tokenizer_family VARCHAR(100) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS counting_mode VARCHAR(20) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS unknown_capabilities JSONB DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS capacity_fingerprint VARCHAR(64) DEFAULT NULL;

COMMENT ON COLUMN nexent.model_monitoring_record_t.context_window_tokens IS 'Resolved total combined model context window for this request';
COMMENT ON COLUMN nexent.model_monitoring_record_t.default_output_reserve_tokens IS 'Default output allowance reserved before input context construction';
COMMENT ON COLUMN nexent.model_monitoring_record_t.capability_profile_version IS 'Version of the resolved capacity profile for this request';
COMMENT ON COLUMN nexent.model_monitoring_record_t.capacity_source IS 'Dominant source of resolved capacity fields for this request';
COMMENT ON COLUMN nexent.model_monitoring_record_t.requested_output_tokens IS 'Output tokens requested or reserved during capacity resolution';
COMMENT ON COLUMN nexent.model_monitoring_record_t.provider_input_limit_tokens IS 'Resolved provider input-token limit used by context management';
COMMENT ON COLUMN nexent.model_monitoring_record_t.tokenizer_family IS 'Tokenizer family used for request token counting';
COMMENT ON COLUMN nexent.model_monitoring_record_t.counting_mode IS 'Token counting mode for the request: exact or estimated';
COMMENT ON COLUMN nexent.model_monitoring_record_t.unknown_capabilities IS 'Structured list of capacity capabilities unknown at resolution time';
COMMENT ON COLUMN nexent.model_monitoring_record_t.capacity_fingerprint IS 'Fingerprint of the resolved model capacity snapshot';
