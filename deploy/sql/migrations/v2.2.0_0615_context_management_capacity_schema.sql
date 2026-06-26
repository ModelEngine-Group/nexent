-- Migration kind: REQUIRED_SCHEMA
-- Required for: all upgraded deployments before running W1/W2 context-management code.
-- Reason: new code reads/writes these model capacity, monitoring snapshot, and agent override columns.

-- ============================================================
-- W1: Add explicit model token-capacity fields to model_record_t
-- ============================================================
-- All columns are nullable and additive; legacy max_tokens stays as a deprecated
-- output-cap alias until consumers migrate.

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS context_window_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS max_input_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS max_output_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS default_output_reserve_tokens INTEGER DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS tokenizer_family VARCHAR(100) DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS capacity_source VARCHAR(100) DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS capability_profile_version VARCHAR(100) DEFAULT NULL;

COMMENT ON COLUMN nexent.model_record_t.context_window_tokens IS 'Total combined input/output context window in tokens, when the provider uses a combined window. Nullable.';
COMMENT ON COLUMN nexent.model_record_t.max_input_tokens IS 'Provider hard input-token limit when distinct from the combined window. Nullable.';
COMMENT ON COLUMN nexent.model_record_t.max_output_tokens IS 'Provider-supported or operator-configured completion-output cap. Replaces the ambiguous LLM meaning of max_tokens. Nullable.';
COMMENT ON COLUMN nexent.model_record_t.default_output_reserve_tokens IS 'Default output allowance reserved per request before constructing input context. Nullable.';
COMMENT ON COLUMN nexent.model_record_t.tokenizer_family IS 'Token-counting strategy or provider/model tokenizer identifier mapped via tokenizer_registry. Nullable.';
COMMENT ON COLUMN nexent.model_record_t.capacity_source IS 'Source of the persisted capacity value. Optional values: operator, profile, provider_candidate, legacy, unknown.';
COMMENT ON COLUMN nexent.model_record_t.capability_profile_version IS 'Version of the approved provider/model capability profile used by the request, e.g. openai/gpt-4o@1.';

-- ============================================================
-- W1: Persist resolved model capacity snapshot fields on monitoring records
-- ============================================================

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

-- ============================================================
-- W2: Add per-agent requested_output_tokens override
-- ============================================================

ALTER TABLE nexent.ag_tenant_agent_t
  ADD COLUMN IF NOT EXISTS requested_output_tokens INTEGER NULL;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.requested_output_tokens IS
  'Per-agent override for W2 requested_output_tokens. NULL means inherit '
  'the resolved model-level default. Must satisfy 0 < value <= '
  'max_output_tokens from the resolved W1 capacity at save time.';

-- ============================================================
-- W2: Add safe input budget snapshot fields to model monitoring records
-- ============================================================

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
