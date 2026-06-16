-- W1: Add explicit model token-capacity fields to model_record_t.
-- See ADR doc/working/context-management-workstreams/W1_ADR_Capability_Catalog_Storage_and_Fingerprint.md.
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
