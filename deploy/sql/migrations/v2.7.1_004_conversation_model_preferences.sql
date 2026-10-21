-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Extend existing conversation configuration; preferences never enter model-visible metadata.
ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS model_parameter_preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS model_parameter_preferences_version INTEGER NOT NULL DEFAULT 0;
COMMENT ON COLUMN nexent.conversation_record_t.model_parameter_preferences IS
    'Explicit parameter preferences keyed by outlet ID for this conversation; no credentials or default-value copies.';
COMMENT ON COLUMN nexent.conversation_record_t.model_parameter_preferences_version IS
    'Optimistic revision of conversation model preferences; independent of runtime metadata and Workbench configuration.';
