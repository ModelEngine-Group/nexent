-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

BEGIN;

-- Keep schema inspection, consolidation and removal atomic with concurrent writers.
LOCK TABLE nexent.ag_tenant_agent_t IN ACCESS EXCLUSIVE MODE;

DO $migration$
DECLARE
    legacy_column_count integer;
BEGIN
    SELECT count(*) INTO legacy_column_count
    FROM information_schema.columns
    WHERE table_schema = 'nexent'
      AND table_name = 'ag_tenant_agent_t'
      AND column_name IN ('constraint_prompt', 'few_shots_prompt');

    -- A completed migration is safe to execute again after both columns are gone.
    IF legacy_column_count = 0 THEN
        RETURN;
    END IF;
    IF legacy_column_count <> 2 THEN
        RAISE EXCEPTION 'Expected both legacy Agent prompt columns before consolidation';
    END IF;

    -- Migrate every tenant and version before deploying the single-source runtime.
    -- Preserve literal contents, including code indentation and Unicode characters.
    UPDATE nexent.ag_tenant_agent_t
    SET duty_prompt = CASE
            WHEN btrim(COALESCE(constraint_prompt, ''), E' \t\n\r') <> ''
              OR btrim(COALESCE(few_shots_prompt, ''), E' \t\n\r') <> ''
            THEN concat_ws(E'\n\n',
                CASE WHEN btrim(COALESCE(duty_prompt, ''), E' \t\n\r') <> ''
                     THEN E'# Responsibilities\n' || duty_prompt END,
                CASE WHEN btrim(COALESCE(constraint_prompt, ''), E' \t\n\r') <> ''
                     THEN E'# Constraints\n' || constraint_prompt END,
                CASE WHEN btrim(COALESCE(few_shots_prompt, ''), E' \t\n\r') <> ''
                     THEN E'# Examples\n' || few_shots_prompt END)
            ELSE duty_prompt
        END
    WHERE constraint_prompt IS DISTINCT FROM ''
       OR few_shots_prompt IS DISTINCT FROM '';

    ALTER TABLE nexent.ag_tenant_agent_t
        DROP COLUMN constraint_prompt,
        DROP COLUMN few_shots_prompt;
END;
$migration$;

COMMIT;
