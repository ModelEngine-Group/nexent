-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

BEGIN;

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
    END,
    constraint_prompt = '',
    few_shots_prompt = ''
WHERE constraint_prompt IS DISTINCT FROM ''
   OR few_shots_prompt IS DISTINCT FROM '';

COMMIT;
