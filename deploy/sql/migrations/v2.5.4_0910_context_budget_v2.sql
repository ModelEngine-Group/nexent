-- Context Budget V2 final-state migration.
-- Deployment contract: stop all application instances before applying this file.
BEGIN;

DO $$
DECLARE
    table_exists BOOLEAN;
    schema_name CONSTANT TEXT := 'nexent';
    monitoring_table_name CONSTANT TEXT := 'model_monitoring_record_t';
BEGIN
    SELECT to_regclass('nexent.model_monitoring_record_t') IS NOT NULL
      INTO table_exists;
    IF NOT table_exists THEN
        RAISE EXCEPTION 'nexent.model_monitoring_record_t must exist before Context Budget V2 migration';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = schema_name
           AND table_name = monitoring_table_name
           AND column_name = 'provider_input_limit_tokens'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = schema_name
           AND table_name = monitoring_table_name
           AND column_name = 'effective_input_limit_tokens'
    ) THEN
        ALTER TABLE nexent.model_monitoring_record_t
            RENAME COLUMN provider_input_limit_tokens TO effective_input_limit_tokens;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = schema_name
           AND table_name = monitoring_table_name
           AND column_name = 'budget_provider_input_limit_tokens'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = schema_name
           AND table_name = monitoring_table_name
           AND column_name = 'budget_effective_input_limit_tokens'
    ) THEN
        ALTER TABLE nexent.model_monitoring_record_t
            RENAME COLUMN budget_provider_input_limit_tokens
            TO budget_effective_input_limit_tokens;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = schema_name
           AND table_name = monitoring_table_name
           AND column_name = 'budget_soft_limit_ratio'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = schema_name
           AND table_name = monitoring_table_name
           AND column_name = 'budget_compaction_trigger_ratio'
    ) THEN
        ALTER TABLE nexent.model_monitoring_record_t
            RENAME COLUMN budget_soft_limit_ratio
            TO budget_compaction_trigger_ratio;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = schema_name
           AND table_name = monitoring_table_name
           AND column_name = 'budget_soft_input_budget_tokens'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = schema_name
           AND table_name = monitoring_table_name
           AND column_name = 'budget_compaction_trigger_threshold_tokens'
    ) THEN
        ALTER TABLE nexent.model_monitoring_record_t
            RENAME COLUMN budget_soft_input_budget_tokens
            TO budget_compaction_trigger_threshold_tokens;
    END IF;
END $$;

-- Fresh installs create the final columns in init.sql, while historical
-- migrations may subsequently add the legacy columns. Merge and remove those
-- duplicate legacy columns before backfilling the V2 metadata.
DO $$
DECLARE
    schema_name CONSTANT TEXT := 'nexent';
    monitoring_table_name CONSTANT TEXT := 'model_monitoring_record_t';
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=schema_name AND table_name=monitoring_table_name AND column_name='provider_input_limit_tokens')
       AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=schema_name AND table_name=monitoring_table_name AND column_name='effective_input_limit_tokens') THEN
        UPDATE nexent.model_monitoring_record_t
           SET effective_input_limit_tokens = provider_input_limit_tokens
         WHERE effective_input_limit_tokens IS NULL
           AND provider_input_limit_tokens IS NOT NULL;
        ALTER TABLE nexent.model_monitoring_record_t DROP COLUMN provider_input_limit_tokens;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=schema_name AND table_name=monitoring_table_name AND column_name='budget_provider_input_limit_tokens')
       AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=schema_name AND table_name=monitoring_table_name AND column_name='budget_effective_input_limit_tokens') THEN
        UPDATE nexent.model_monitoring_record_t
           SET budget_effective_input_limit_tokens = budget_provider_input_limit_tokens
         WHERE budget_effective_input_limit_tokens IS NULL
           AND budget_provider_input_limit_tokens IS NOT NULL;
        ALTER TABLE nexent.model_monitoring_record_t DROP COLUMN budget_provider_input_limit_tokens;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=schema_name AND table_name=monitoring_table_name AND column_name='budget_soft_limit_ratio')
       AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=schema_name AND table_name=monitoring_table_name AND column_name='budget_compaction_trigger_ratio') THEN
        UPDATE nexent.model_monitoring_record_t
           SET budget_compaction_trigger_ratio = budget_soft_limit_ratio
         WHERE budget_compaction_trigger_ratio IS NULL
           AND budget_soft_limit_ratio IS NOT NULL;
        ALTER TABLE nexent.model_monitoring_record_t DROP COLUMN budget_soft_limit_ratio;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=schema_name AND table_name=monitoring_table_name AND column_name='budget_soft_input_budget_tokens')
       AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=schema_name AND table_name=monitoring_table_name AND column_name='budget_compaction_trigger_threshold_tokens') THEN
        UPDATE nexent.model_monitoring_record_t
           SET budget_compaction_trigger_threshold_tokens = budget_soft_input_budget_tokens
         WHERE budget_compaction_trigger_threshold_tokens IS NULL
           AND budget_soft_input_budget_tokens IS NOT NULL;
        ALTER TABLE nexent.model_monitoring_record_t DROP COLUMN budget_soft_input_budget_tokens;
    END IF;
END $$;

ALTER TABLE nexent.model_monitoring_record_t
    ADD COLUMN IF NOT EXISTS budget_schema_version INTEGER,
    ADD COLUMN IF NOT EXISTS budget_compaction_trigger_ratio_source VARCHAR(32),
    ADD COLUMN IF NOT EXISTS budget_compaction_target_ratio FLOAT,
    ADD COLUMN IF NOT EXISTS budget_compaction_target_ratio_source VARCHAR(32),
    ADD COLUMN IF NOT EXISTS budget_compaction_target_tokens INTEGER;

UPDATE nexent.model_monitoring_record_t
SET budget_schema_version = COALESCE(budget_schema_version, 1),
    budget_compaction_trigger_ratio_source = COALESCE(
        budget_compaction_trigger_ratio_source,
        'legacy_payload'
    ),
    budget_compaction_target_ratio = COALESCE(budget_compaction_target_ratio, 0.6),
    budget_compaction_target_ratio_source = COALESCE(
        budget_compaction_target_ratio_source,
        'code_default'
    ),
    budget_compaction_target_tokens = COALESCE(
        budget_compaction_target_tokens,
        FLOOR(budget_effective_input_limit_tokens * 0.6)::INTEGER
    )
WHERE budget_schema_version IS NULL
  AND (
      budget_fingerprint IS NOT NULL
      OR budget_effective_input_limit_tokens IS NOT NULL
      OR budget_compaction_trigger_threshold_tokens IS NOT NULL
  );

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM nexent.model_monitoring_record_t
        WHERE budget_schema_version = 1
          AND (budget_fingerprint IS NOT NULL
            OR budget_effective_input_limit_tokens IS NOT NULL
            OR budget_compaction_trigger_threshold_tokens IS NOT NULL)
          AND (
              budget_schema_version IS NULL
              OR budget_compaction_target_ratio IS DISTINCT FROM 0.6
              OR (
                  budget_effective_input_limit_tokens IS NOT NULL
                  AND budget_compaction_target_tokens IS DISTINCT FROM
                      FLOOR(budget_effective_input_limit_tokens * 0.6)::INTEGER
              )
          )
    ) THEN
        RAISE EXCEPTION 'Context Budget V2 historical backfill consistency check failed';
    END IF;
END $$;

ALTER TABLE nexent.model_monitoring_record_t
    DROP COLUMN IF EXISTS budget_hard_input_budget_tokens;

COMMENT ON COLUMN nexent.model_monitoring_record_t.effective_input_limit_tokens
    IS 'Resolved effective provider input-token limit used by context management';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_schema_version
    IS 'Persisted context-budget contract schema version; 1 denotes migrated V1 history';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_effective_input_limit_tokens
    IS 'Effective Input Limit after applying the output reserve';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_compaction_trigger_ratio
    IS 'Compaction Trigger Threshold ratio';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_compaction_trigger_ratio_source
    IS 'Source of the Compaction Trigger Threshold ratio';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_compaction_trigger_threshold_tokens
    IS 'Effective input token threshold that triggers compaction';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_compaction_target_ratio
    IS 'Compaction Target ratio';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_compaction_target_ratio_source
    IS 'Source of the Compaction Target ratio';
COMMENT ON COLUMN nexent.model_monitoring_record_t.budget_compaction_target_tokens
    IS 'Desired effective input token count after compaction';

COMMIT;
