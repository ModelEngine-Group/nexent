-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Retire private generation templates. SDK prompt resources remain application assets.
ALTER TABLE IF EXISTS nexent.ag_tenant_agent_t
    DROP COLUMN IF EXISTS prompt_template_id,
    DROP COLUMN IF EXISTS prompt_template_name;

-- Dropping the table also removes its indexes, trigger and owned serial sequence.
DROP TABLE IF EXISTS nexent.ag_prompt_template_t;

-- The historical migration used an unqualified function name.
DROP FUNCTION IF EXISTS public.update_ag_prompt_template_update_time();
DROP FUNCTION IF EXISTS nexent.update_ag_prompt_template_update_time();

-- Also handle installations where the sequence was not owned by the table.
DROP SEQUENCE IF EXISTS nexent.ag_prompt_template_t_template_id_seq;
