-- Add W2 safe input budget snapshot fields to model monitoring records.

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_fingerprint VARCHAR(64) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_w1_fingerprint VARCHAR(64) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_requested_output_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_output_reserve_source VARCHAR(32) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_provider_input_limit_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_uncertainty_reserve_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_uncertainty_reserve_basis VARCHAR(64) DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_soft_limit_ratio FLOAT DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_soft_input_budget_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_hard_input_budget_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_monitoring_record_t
ADD COLUMN IF NOT EXISTS budget_warnings JSONB DEFAULT NULL;

COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_fingerprint IS 'Fingerprint of the resolved W2 safe input budget snapshot';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_w1_fingerprint IS 'W1 capacity fingerprint consumed by the W2 budget snapshot';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_requested_output_tokens IS 'W2 trusted requested output tokens used at dispatch';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_output_reserve_source IS 'Source of the W2 requested output token reserve';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_provider_input_limit_tokens IS 'Provider input limit after applying the W2 output reserve';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_uncertainty_reserve_tokens IS 'Additional W2 uncertainty reserve deducted from input budget';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_uncertainty_reserve_basis IS 'Basis used for the W2 uncertainty reserve';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_soft_limit_ratio IS 'W2 soft input budget ratio';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_soft_input_budget_tokens IS 'W2 soft input budget where proactive compression begins';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_hard_input_budget_tokens IS 'W2 hard input budget consumed by W3 final fit';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_warnings IS 'Structured W2 budget warnings active for this request';
