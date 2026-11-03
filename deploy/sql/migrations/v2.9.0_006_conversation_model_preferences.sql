-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_record_t ADD COLUMN IF NOT EXISTS selected_model_id INTEGER;
COMMENT ON COLUMN nexent.conversation_record_t.selected_model_id IS
    'Root model selected for this Agent conversation; NULL inherits the Agent default.';

-- Extend existing conversation configuration; preferences never enter model-visible metadata.
ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS model_parameter_preferences JSONB NOT NULL DEFAULT '{}'::jsonb;
-- Remove the retired revision from earlier deployments of this PR.
ALTER TABLE nexent.conversation_record_t
    DROP COLUMN IF EXISTS model_parameter_preferences_version;
COMMENT ON COLUMN nexent.conversation_record_t.model_parameter_preferences IS
    'Explicit parameter preferences keyed by outlet ID for this conversation; no credentials or default-value copies.';
