-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Add resolved outlet storage without inferring legacy model capabilities.
-- Existing configuration values remain in their original columns.
ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS reasoning_supported BOOLEAN,
    ADD COLUMN IF NOT EXISTS reasoning_controls JSONB,
    ADD COLUMN IF NOT EXISTS native_tool_call_supported BOOLEAN,
    ADD COLUMN IF NOT EXISTS structured_output_supported BOOLEAN,
    ADD COLUMN IF NOT EXISTS temperature_supported BOOLEAN,
    ADD COLUMN IF NOT EXISTS top_p_supported BOOLEAN,
    ADD COLUMN IF NOT EXISTS input_modalities JSONB,
    ADD COLUMN IF NOT EXISTS output_modalities JSONB,
    ADD COLUMN IF NOT EXISTS enable_thinking BOOLEAN,
    ADD COLUMN IF NOT EXISTS reasoning_effort VARCHAR(30),
    ADD COLUMN IF NOT EXISTS reasoning_budget_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS protocol_id VARCHAR(30),
    ADD COLUMN IF NOT EXISTS resolved_profile JSONB,
    ADD COLUMN IF NOT EXISTS profile_schema_version INTEGER,
    ADD COLUMN IF NOT EXISTS config_revision INTEGER NOT NULL DEFAULT 1;

COMMENT ON COLUMN nexent.model_record_t.reasoning_supported IS 'Reasoning support: true supported, false unsupported, NULL unknown.';
COMMENT ON COLUMN nexent.model_record_t.reasoning_controls IS 'Declared reasoning control domains; NULL unknown, empty array no controls.';
COMMENT ON COLUMN nexent.model_record_t.native_tool_call_supported IS 'Native tool call support; NULL unknown, not an execution guarantee.';
COMMENT ON COLUMN nexent.model_record_t.structured_output_supported IS 'Structured output support; NULL unknown, formats require binding.';
COMMENT ON COLUMN nexent.model_record_t.temperature_supported IS 'Temperature control support; NULL unknown, separate from parameter value.';
COMMENT ON COLUMN nexent.model_record_t.top_p_supported IS 'Top-p control support; NULL unknown, separate from parameter value.';
COMMENT ON COLUMN nexent.model_record_t.input_modalities IS 'Unique supported input modality names; NULL unknown, empty array no modalities.';
COMMENT ON COLUMN nexent.model_record_t.output_modalities IS 'Unique supported output modality names; NULL unknown, empty array no modalities.';
COMMENT ON COLUMN nexent.model_record_t.enable_thinking IS 'Saved thinking switch; NULL omitted unless marked as explicit JSON null.';
COMMENT ON COLUMN nexent.model_record_t.reasoning_effort IS 'Saved reasoning effort; NULL omitted unless marked as explicit JSON null.';
COMMENT ON COLUMN nexent.model_record_t.reasoning_budget_tokens IS 'Saved reasoning token budget; sentinel values require explicit declaration.';
COMMENT ON COLUMN nexent.model_record_t.protocol_id IS 'Registered model protocol; NULL only before resolved outlet migration completes.';
COMMENT ON COLUMN nexent.model_record_t.resolved_profile IS 'Remaining resolved rules, bindings and provenance; no copies of dedicated column values.';
COMMENT ON COLUMN nexent.model_record_t.profile_schema_version IS 'Persisted resolved profile schema version; NULL for pre-migration rows.';
COMMENT ON COLUMN nexent.model_record_t.config_revision IS 'Outlet configuration revision for optimistic updates; initial value 1.';
