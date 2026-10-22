-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Nexent merged SQL migrations: v2.7.0
-- Previous release tag: v2.6.1
-- Source bodies are embedded byte-for-byte in deployment order.
-- Do not reorder or rewrite sections without equivalence validation.

-- Source migration: v2.6.0_z_agent_repository_icon_url.sql
-- Source SHA-256: 5ffc0a0389f5ed3ab0538139f0870f2d35fb10fdcbb91a62555774e886842d89

-- Repository listings now store an optional uploaded image URL. Legacy emoji
-- values fall back to the deterministic agent icon after this migration.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'nexent' AND table_name = 'ag_agent_repository_t'
      AND column_name = 'icon'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'nexent' AND table_name = 'ag_agent_repository_t'
      AND column_name = 'icon_url'
  ) THEN
    ALTER TABLE nexent.ag_agent_repository_t RENAME COLUMN icon TO icon_url;
    UPDATE nexent.ag_agent_repository_t SET icon_url = NULL;
  END IF;
END $$;

ALTER TABLE nexent.ag_agent_repository_t
  ALTER COLUMN icon_url TYPE VARCHAR(1024);

COMMENT ON COLUMN nexent.ag_agent_repository_t.icon_url IS
  'Repository icon URL; NULL uses the agent ID based default icon';


-- Source migration: v2.6.1_001_remove_human_interaction.sql
-- Source SHA-256: 08f51328a6de8a7537265d5087be872b33ea8f1282fc892a0f5b1f4baa364479

-- Deploy only after all processes using the retired interaction engine have stopped.
-- Ordinary conversation messages and units are intentionally preserved.
DROP TABLE IF EXISTS nexent.human_event_t;
DROP TABLE IF EXISTS nexent.human_execution_t;
DROP TABLE IF EXISTS nexent.human_request_t;
DROP TABLE IF EXISTS nexent.human_run_t;
-- This function is used exclusively by the four tables removed above.
DROP FUNCTION IF EXISTS nexent.human_interaction_audit_timestamp();


-- Source migration: v2.6.1_002_remove_dev_models_menu.sql
-- Source SHA-256: e1c57d58d6754351c05820017e0bc24774c8d2728151ca517a186631338e35af

-- Remove the model management page from the DEV role menu.
-- Developers must not see or manage models; they only consume
-- administrator-configured models. RESOURCE MODEL READ is kept so
-- model pickers in agent editing keep working.
-- Pattern follows v2.3 migration that removed ASSET_OWNER /owner-manage.
DELETE FROM nexent.role_permission_t
WHERE user_role = 'DEV'
  AND permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype = '/models';


-- Source migration: v2.6.2_001_agent_workbench.sql
-- Source SHA-256: 5b210092620c8088caf1f39514a54c2c35d74bd578d26cd24d95ce224af241e7

-- Add protected platform Agent identity for the intelligent workbench.
ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS system_key VARCHAR(100),
    ADD COLUMN IF NOT EXISTS agent_origin VARCHAR(20) NOT NULL DEFAULT 'USER',
    ADD COLUMN IF NOT EXISTS system_revision VARCHAR(100);

COMMENT ON COLUMN nexent.ag_tenant_agent_t.system_key IS
    'Stable platform-owned Agent key; NULL for user-created Agents';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.agent_origin IS
    'Agent ownership origin: USER or SYSTEM';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.system_revision IS
    'Server-controlled Nexent release revision applied to a system Agent';

CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_system_agent_active_draft
    ON nexent.ag_tenant_agent_t (tenant_id, system_key)
    WHERE version_no = 0
      AND delete_flag != 'Y'
      AND system_key IS NOT NULL;

-- Creation permissions are required by the server-side NL2 adapters. Permission
-- IDs are migration-owned and explicit; ordinary USER is intentionally excluded.
WITH required_grants (role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
) AS (
    VALUES
        (1701, 'SU',          'RESOURCE', 'AGENT', 'CREATE'),
        (1702, 'ADMIN',       'RESOURCE', 'AGENT', 'CREATE'),
        (1703, 'DEV',         'RESOURCE', 'AGENT', 'CREATE'),
        (1704, 'ASSET_OWNER', 'RESOURCE', 'AGENT', 'CREATE'),
        (1705, 'SPEED',       'RESOURCE', 'AGENT', 'CREATE'),
        (1706, 'SU',          'RESOURCE', 'SKILL', 'CREATE'),
        (1707, 'ADMIN',       'RESOURCE', 'SKILL', 'CREATE'),
        (1708, 'DEV',         'RESOURCE', 'SKILL', 'CREATE'),
        (1709, 'ASSET_OWNER', 'RESOURCE', 'SKILL', 'CREATE'),
        (1710, 'SPEED',       'RESOURCE', 'SKILL', 'CREATE')
)
INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
)
SELECT
    required_grants.role_permission_id,
    required_grants.user_role,
    required_grants.permission_category,
    required_grants.permission_type,
    required_grants.permission_subtype
FROM required_grants
WHERE NOT EXISTS (
    SELECT 1
    FROM nexent.role_permission_t AS existing
    WHERE existing.user_role = required_grants.user_role
      AND existing.permission_category = required_grants.permission_category
      AND existing.permission_type = required_grants.permission_type
      AND existing.permission_subtype = required_grants.permission_subtype
);

-- Persist the canonical Workbench declaration and its optimistic-lock version.
ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS workbench_config JSONB,
    ADD COLUMN IF NOT EXISTS workbench_config_version INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN nexent.conversation_record_t.workbench_config IS
    'Canonical schema-v3 Workbench conversation declaration; resolved runtime artifacts are never persisted';

COMMENT ON COLUMN nexent.conversation_record_t.workbench_config_version IS
    'Monotonic optimistic-lock version for workbench_config';

-- Source migration: v2.7.1_005_unify_agent_prompts.sql
-- Source SHA-256: 745d2947a26ca63bd3144d7dacfb711535a076ba4656f329a7bbcd06a12604ca

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

-- End source migration: v2.7.1_005_unify_agent_prompts.sql

-- Source migration: v2.7.1_006_unify_marketplace_agent_prompts.sql
-- Source SHA-256: 1ef6418005e4fdbb9afda4defdfbb7903e82b2980ede3a2fe161b68438321be8

-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Preserve published instructions from each frozen snapshot, never from live drafts.
BEGIN;
LOCK TABLE nexent.ag_agent_repository_t IN ACCESS EXCLUSIVE MODE;

CREATE FUNCTION pg_temp.unify_marketplace_prompt(fields JSONB) RETURNS JSONB
LANGUAGE plpgsql AS $function$
DECLARE
    field_name TEXT;
    alias_pair TEXT[];
    base_prompt TEXT;
    constraint_text TEXT;
    example_text TEXT;
    merged TEXT;
BEGIN
    IF jsonb_typeof(fields) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'Marketplace agent entries must be JSON objects';
    END IF;
    FOREACH field_name IN ARRAY ARRAY[
        'prompt', 'duty_prompt', 'constraint_prompt', 'constraints_prompt',
        'few_shots_prompt', 'few_shot_prompts'
    ] LOOP
        IF fields ? field_name AND jsonb_typeof(fields -> field_name) NOT IN ('string', 'null') THEN
            RAISE EXCEPTION 'Marketplace prompt field % must be a string or null', field_name;
        END IF;
    END LOOP;
    FOREACH alias_pair SLICE 1 IN ARRAY ARRAY[
        ['prompt', 'duty_prompt'],
        ['constraint_prompt', 'constraints_prompt'],
        ['few_shots_prompt', 'few_shot_prompts']
    ] LOOP
        IF fields ? alias_pair[2] THEN
            IF fields ? alias_pair[1] AND fields -> alias_pair[1] IS DISTINCT FROM fields -> alias_pair[2] THEN
                RAISE EXCEPTION 'Conflicting marketplace prompt aliases: % and %', alias_pair[1], alias_pair[2];
            END IF;
            IF NOT fields ? alias_pair[1] THEN
                fields := fields || jsonb_build_object(alias_pair[1], fields -> alias_pair[2]);
            END IF;
            fields := fields - alias_pair[2];
        END IF;
    END LOOP;

    base_prompt := fields ->> 'prompt';
    constraint_text := fields ->> 'constraint_prompt';
    example_text := fields ->> 'few_shots_prompt';
    IF btrim(COALESCE(constraint_text, ''), E' \t\n\r') <> ''
       OR btrim(COALESCE(example_text, ''), E' \t\n\r') <> '' THEN
        merged := concat_ws(E'\n\n',
            CASE WHEN btrim(COALESCE(base_prompt, ''), E' \t\n\r') <> ''
                 THEN E'# Responsibilities\n' || base_prompt END,
            CASE WHEN btrim(COALESCE(constraint_text, ''), E' \t\n\r') <> ''
                 THEN E'# Constraints\n' || constraint_text END,
            CASE WHEN btrim(COALESCE(example_text, ''), E' \t\n\r') <> ''
                 THEN E'# Examples\n' || example_text END);
        fields := fields || jsonb_build_object('prompt', merged);
    END IF;
    RETURN fields - 'constraint_prompt' - 'few_shots_prompt';
END;
$function$;

DO $migration$
DECLARE
    listing RECORD;
    agent_entry RECORD;
    normalized_agents JSONB;
BEGIN
    -- Include historical and deleted listings so every later reader sees one format.
    FOR listing IN SELECT agent_repository_id, agent_info_json FROM nexent.ag_agent_repository_t LOOP
        IF jsonb_typeof(listing.agent_info_json) IS DISTINCT FROM 'object'
           OR jsonb_typeof(listing.agent_info_json -> 'agent_info') IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'Invalid agent_info in marketplace listing %', listing.agent_repository_id;
        END IF;
        normalized_agents := '{}'::JSONB;
        FOR agent_entry IN SELECT key, value FROM jsonb_each(listing.agent_info_json -> 'agent_info') LOOP
            normalized_agents := normalized_agents || jsonb_build_object(
                agent_entry.key, pg_temp.unify_marketplace_prompt(agent_entry.value));
        END LOOP;
        IF normalized_agents IS DISTINCT FROM listing.agent_info_json -> 'agent_info' THEN
            -- Keep publication identity, version, audit metadata and all other JSON unchanged.
            UPDATE nexent.ag_agent_repository_t
            SET agent_info_json = jsonb_set(agent_info_json, '{agent_info}', normalized_agents)
            WHERE agent_repository_id = listing.agent_repository_id;
        END IF;
    END LOOP;
END;
$migration$;

DROP FUNCTION pg_temp.unify_marketplace_prompt(JSONB);
COMMIT;

-- End source migration: v2.7.1_006_unify_marketplace_agent_prompts.sql

-- Source migration: v2.7.1_009_rename_agent_prompt_column.sql
-- Source SHA-256: 9fe0ed28d22fe224107997e63febc4a604be876c7e42513104e41ad94f4aadaa

-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Run after prompt section consolidation; rename metadata without rewriting values.
BEGIN;
LOCK TABLE nexent.ag_tenant_agent_t IN ACCESS EXCLUSIVE MODE;

DO $migration$
DECLARE
    has_legacy BOOLEAN;
    has_prompt BOOLEAN;
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent' AND table_name = 'ag_tenant_agent_t'
          AND column_name IN ('constraint_prompt', 'few_shots_prompt')
    ) THEN
        RAISE EXCEPTION 'Consolidate legacy Agent prompt sections before renaming the prompt column';
    END IF;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent' AND table_name = 'ag_tenant_agent_t' AND column_name = 'duty_prompt'
    ), EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent' AND table_name = 'ag_tenant_agent_t' AND column_name = 'prompt'
    ) INTO has_legacy, has_prompt;

    IF has_legacy AND has_prompt THEN
        RAISE EXCEPTION 'Both duty_prompt and prompt columns exist; resolve the ambiguous Agent schema first';
    ELSIF has_legacy THEN
        ALTER TABLE nexent.ag_tenant_agent_t RENAME COLUMN duty_prompt TO prompt;
    ELSIF NOT has_prompt THEN
        RAISE EXCEPTION 'Neither duty_prompt nor prompt exists in the Agent table';
    END IF;
END;
$migration$;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.prompt
    IS 'Complete Agent instructions including responsibilities, constraints and examples';
COMMIT;

-- End source migration: v2.7.1_009_rename_agent_prompt_column.sql
