-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_record_t ADD COLUMN IF NOT EXISTS selected_model_id INTEGER;
COMMENT ON COLUMN nexent.conversation_record_t.selected_model_id IS
    'Root model selected for this Agent conversation; NULL inherits the Agent default.';

-- Upgrade only historical Workbench declarations. New preferences win per field.
-- Never assign historical choices to an arbitrary model when its identity is missing.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM nexent.conversation_record_t
        WHERE jsonb_typeof(workbench_config->'generation_config') = 'object'
          AND COALESCE(workbench_config->>'model_parameters_source', 'legacy_generation') = 'legacy_generation'
          AND COALESCE(workbench_config->>'model_id', selected_model_id::text) IS NULL
          AND (workbench_config->'generation_config') - 'requested_output_tokens' <> '{}'::jsonb
    ) THEN
        RAISE EXCEPTION 'Workbench model parameter migration requires a model_id; no historical settings were discarded';
    END IF;
END $$;

WITH historical AS (
    SELECT conversation_id, workbench_config AS config,
           workbench_config->'generation_config' AS generation,
           COALESCE(workbench_config->>'model_id', selected_model_id::text) AS model_key
    FROM nexent.conversation_record_t
    WHERE jsonb_typeof(workbench_config) = 'object'
      AND (workbench_config ? 'generation_config' OR workbench_config ? 'model_parameters_source'
           OR workbench_config->>'schema_version' = '3')
), converted AS (
    SELECT *, CASE
        WHEN model_key IS NOT NULL
         AND COALESCE(config->>'model_parameters_source', 'legacy_generation') = 'legacy_generation'
        THEN jsonb_strip_nulls(jsonb_build_object(
            'temperature', generation->'temperature',
            'top_p', generation->'top_p',
            'enable_thinking', generation->'deep_thinking',
            'reasoning_budget_tokens', CASE WHEN generation->>'deep_thinking' = 'true'
                AND COALESCE((generation->>'reasoning_budget_tokens')::bigint, 0) > 0
                THEN generation->'reasoning_budget_tokens' END,
            'reasoning_effort', CASE WHEN generation->>'deep_thinking' = 'true'
                AND COALESCE((generation->>'reasoning_budget_tokens')::bigint, 0) = 0
                AND generation->>'thinking_effort' <> 'auto'
                THEN generation->'thinking_effort' END
        )) ELSE '{}'::jsonb END AS preferences
    FROM historical
)
UPDATE nexent.conversation_record_t AS target
SET selected_model_id = COALESCE(target.selected_model_id, converted.model_key::integer),
    model_parameter_preferences = CASE WHEN converted.preferences <> '{}'::jsonb
        THEN target.model_parameter_preferences || jsonb_build_object(converted.model_key,
            (CASE WHEN target.model_parameter_preferences->converted.model_key ?| ARRAY['reasoning_effort', 'reasoning_budget_tokens']
                    OR target.model_parameter_preferences->converted.model_key->>'enable_thinking' = 'false'
                THEN converted.preferences - 'reasoning_effort' - 'reasoning_budget_tokens'
                ELSE converted.preferences END)
            || COALESCE(target.model_parameter_preferences->converted.model_key, '{}'::jsonb))
        ELSE target.model_parameter_preferences END,
    model_parameter_preferences_version = target.model_parameter_preferences_version
        + CASE WHEN converted.preferences <> '{}'::jsonb
            OR (converted.model_key IS NOT NULL AND target.selected_model_id IS NULL) THEN 1 ELSE 0 END,
    workbench_config = (converted.config - 'generation_config' - 'model_parameters_source' - 'model_id')
        || jsonb_build_object('schema_version', 4)
        || CASE WHEN converted.generation->>'requested_output_tokens' IS NOT NULL
            THEN jsonb_build_object('requested_output_tokens', converted.generation->'requested_output_tokens')
            ELSE '{}'::jsonb END,
    workbench_config_version = target.workbench_config_version + 1,
    updated_by = 'migration:session-model-parameters',
    update_time = CURRENT_TIMESTAMP
FROM converted
WHERE target.conversation_id = converted.conversation_id;
