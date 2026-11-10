-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Retire identifiable bootstrap and administrator-registration voice seeds.
-- Keep ambiguous records and tenant-wide voice settings that have no model ID.
WITH seed_candidates AS (
    SELECT model_id, tenant_id, model_type, created_by, create_time
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
      AND ssl_verify IS TRUE
      AND max_tokens = 0
      AND used_token = 0
      AND connect_status = 'unavailable'
      AND updated_by IS NOT DISTINCT FROM created_by
    FOR UPDATE
), registration_pairs AS (
    -- The old registration handler inserted TTS then STT after creating the membership.
    SELECT tts.model_id AS tts_id, stt.model_id AS stt_id
    FROM seed_candidates AS tts
    JOIN seed_candidates AS stt
      ON stt.model_id = tts.model_id::bigint + 1
     AND stt.tenant_id = tts.tenant_id
     AND stt.created_by = tts.created_by
     AND stt.create_time BETWEEN tts.create_time AND tts.create_time + INTERVAL '5 seconds'
    WHERE tts.model_type = 'tts'
      AND stt.model_type = 'stt'
      AND EXISTS (
          SELECT 1
          FROM nexent.user_tenant_t AS membership
          WHERE membership.user_id = tts.created_by
            AND membership.tenant_id = tts.tenant_id
            -- Model timestamps in old databases are rounded to whole seconds.
            AND membership.create_time BETWEEN tts.create_time - INTERVAL '1 minute'
                                           AND tts.create_time + INTERVAL '1 second'
      )
), legacy_models AS (
    -- Bootstrap SQL did not record an actor. Include already retired seeds to clear stale defaults.
    SELECT seed.model_id, seed.tenant_id, seed.model_type
    FROM seed_candidates AS seed
    WHERE seed.created_by IS NULL
       OR EXISTS (
           SELECT 1 FROM registration_pairs
           WHERE seed.model_id IN (tts_id, stt_id)
       )
), retired_defaults AS (
    UPDATE nexent.tenant_config_t AS config
    SET delete_flag = 'Y', updated_by = 'system', update_time = CURRENT_TIMESTAMP
    FROM legacy_models AS model
    WHERE config.delete_flag = 'N'
      AND config.config_key = upper(model.model_type) || '_ID'
      AND config.tenant_id IS NOT DISTINCT FROM model.tenant_id
      AND ltrim(btrim(config.config_value), '0') = model.model_id::text
    RETURNING 1
), retired_models AS (
    UPDATE nexent.model_record_t AS model
    SET delete_flag = 'Y', updated_by = 'system', update_time = CURRENT_TIMESTAMP
    FROM legacy_models AS legacy
    WHERE model.model_id = legacy.model_id AND model.delete_flag = 'N'
    RETURNING 1
)
SELECT (SELECT count(*) FROM retired_models) AS retired_models,
       (SELECT count(*) FROM retired_defaults) AS retired_defaults;
