-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Backfill model_monitoring_record_t.model_id.
--
-- Monitoring records used to be written with names only, so the model_id
-- column stayed NULL even though the resource list matches statistics by id.
-- Only unambiguous matches are filled; orphaned history (the configuration
-- has since been deleted or renamed) and duplicate names keep NULL instead of
-- being attributed to the wrong configuration.

BEGIN;

-- 1. Rows that carry the configured display name.
WITH unique_display_names AS (
    SELECT tenant_id, model_type, display_name, MIN(model_id) AS model_id
    FROM nexent.model_record_t
    WHERE delete_flag = 'N'
      AND display_name IS NOT NULL
      AND display_name <> ''
    GROUP BY tenant_id, model_type, display_name
    HAVING COUNT(*) = 1
)
UPDATE nexent.model_monitoring_record_t AS m
SET model_id = u.model_id
FROM unique_display_names AS u
WHERE m.model_id IS NULL
  AND m.delete_flag = 'N'
  AND m.tenant_id = u.tenant_id
  AND m.model_type = u.model_type
  AND m.display_name = u.display_name;

-- 2. Rows whose producer only reported the provider model path (embedding
--    models do this), i.e. display_name equals model_name.
WITH unique_model_paths AS (
    SELECT tenant_id,
           model_type,
           CASE WHEN COALESCE(model_repo, '') = '' THEN NULL
                ELSE model_repo || '/' || model_name END AS repo_path,
           CASE WHEN COALESCE(model_repo, '') = '' THEN model_name END AS bare_name,
           MIN(model_id) AS model_id
    FROM nexent.model_record_t
    WHERE delete_flag = 'N'
    GROUP BY tenant_id, model_type, 3, 4
    HAVING COUNT(*) = 1
)
UPDATE nexent.model_monitoring_record_t AS m
SET model_id = u.model_id
FROM unique_model_paths AS u
WHERE m.model_id IS NULL
  AND m.delete_flag = 'N'
  AND m.display_name IS NOT NULL
  AND m.display_name = m.model_name
  AND m.tenant_id = u.tenant_id
  AND (
        u.model_type = m.model_type
        OR (m.model_type = 'multi_embedding' AND u.model_type = 'embedding')
      )
  AND (m.model_name = u.repo_path OR m.model_name = u.bare_name);

COMMIT;
