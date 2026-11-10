-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Retire all copies of the unconfigured voice models seeded by older Nexent releases.
-- Include retired copies when resolving tenant defaults left by an earlier cleanup.
WITH legacy_models AS (
    SELECT model_id, tenant_id, model_type
    FROM nexent.model_record_t
    WHERE (model_type, model_name, display_name) IN (
        ('tts', 'volcano_tts', 'volcano_tts'),
        ('stt', 'volcano_stt', 'volcano_stt')
    )
      AND model_factory = 'OpenAI-API-Compatible'
      AND COALESCE(btrim(model_repo), '') = ''
      AND COALESCE(btrim(base_url), '') = ''
      AND COALESCE(btrim(api_key), '') = ''
      AND COALESCE(btrim(model_appid), '') = ''
      AND COALESCE(btrim(access_token), '') = ''
    FOR UPDATE
), retired_defaults AS (
    UPDATE nexent.tenant_config_t AS config
    SET delete_flag = 'Y', updated_by = 'system', update_time = CURRENT_TIMESTAMP
    FROM legacy_models AS model
    WHERE config.delete_flag = 'N'
      AND config.config_key = upper(model.model_type) || '_ID'
      AND config.tenant_id IS NOT DISTINCT FROM model.tenant_id
      AND ltrim(btrim(config.config_value), '0') = model.model_id::text
    RETURNING config.tenant_config_id, config.tenant_id, config.config_key
), retired_stt_metadata AS (
    -- The old config writer stored extra STT keys alongside the default model ID.
    -- Preserve them if the tenant has any other active STT selection.
    UPDATE nexent.tenant_config_t AS metadata
    SET delete_flag = 'Y', updated_by = 'system', update_time = CURRENT_TIMESTAMP
    WHERE metadata.delete_flag = 'N'
      AND metadata.config_key IN ('STT_MODEL_FACTORY', 'STT_MODEL_APPID', 'STT_ACCESS_TOKEN')
      AND EXISTS (
          SELECT 1 FROM retired_defaults AS retired
          WHERE retired.config_key = 'STT_ID'
            AND retired.tenant_id IS NOT DISTINCT FROM metadata.tenant_id
      )
      AND NOT EXISTS (
          SELECT 1 FROM nexent.tenant_config_t AS other
          WHERE other.delete_flag = 'N'
            AND other.config_key = 'STT_ID'
            AND other.tenant_id IS NOT DISTINCT FROM metadata.tenant_id
            AND NOT EXISTS (
                SELECT 1 FROM retired_defaults AS retired
                WHERE retired.tenant_config_id = other.tenant_config_id
            )
      )
    RETURNING 1
), retired_models AS (
    UPDATE nexent.model_record_t AS model
    SET delete_flag = 'Y', updated_by = 'system', update_time = CURRENT_TIMESTAMP
    FROM legacy_models AS legacy
    WHERE model.model_id = legacy.model_id AND model.delete_flag = 'N'
    RETURNING 1
)
SELECT (SELECT count(*) FROM retired_models) AS retired_models,
       (SELECT count(*) FROM retired_defaults) AS retired_defaults,
       (SELECT count(*) FROM retired_stt_metadata) AS retired_stt_metadata;
