-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Preserve user overrides while moving processing parameters out of schedules.
INSERT INTO nexent.memory_user_config_t
    (config_id, tenant_id, user_id, value_type, config_key, config_value, created_by, updated_by)
SELECT nextval('nexent.memory_user_config_t_config_id_seq'),
       s.tenant_id, s.user_id, 'single', p.config_key, p.config_value,
       s.created_by, s.updated_by
FROM nexent.memory_dreaming_schedule_t AS s
CROSS JOIN LATERAL (VALUES
    ('DREAMING_MIN_SCORE', s.min_score::text),
    ('DREAMING_MIN_RECALL_COUNT', s.min_recall_count::text),
    ('DREAMING_MIN_UNIQUE_QUERIES', s.min_unique_queries::text),
    ('DREAMING_SOURCE_LIMIT', s.source_limit::text),
    ('DREAMING_LONG_TERM_MAX_CHARS', s.long_term_max_chars::text),
    ('DREAMING_LONG_TERM_LENGTH_TOLERANCE_PERCENT', s.long_term_length_tolerance_percent::text),
    ('DREAMING_SUMMARIZATION_MAX_ATTEMPTS', s.summarization_max_attempts::text)
) AS p(config_key, config_value)
WHERE s.delete_flag = 'N' AND s.agent_id = '__user__'
  AND p.config_value IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM nexent.memory_user_config_t AS c
      WHERE c.user_id = s.user_id AND c.config_key = p.config_key
        AND c.delete_flag = 'N'
  );
