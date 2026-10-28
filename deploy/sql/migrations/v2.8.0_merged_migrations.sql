-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Nexent merged SQL migrations: v2.8.0
-- Previous release tag: v2.7.0
-- Source bodies are embedded in deployment order, byte-for-byte except where a
-- section header notes a deliberate simplification.
-- Do not reorder or rewrite sections without equivalence validation.

-- Source migration: v2.6.1_002_agent_protocol_repair_retry.sql
-- Source SHA-256: 702e0cea2cde4192735335f57b401045f6309ccf76826765aaaf97d587a61163
-- Simplified: ADD COLUMN already sets the default, so the repeated SET DEFAULT is dropped.

ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS enable_protocol_repair_retry BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.enable_protocol_repair_retry IS
    'Whether this agent uses strict output validation and silent protocol repair';


-- Source migration: v2.7.1_001_ind_aidp_search_selectable.sql
-- Source SHA-256: d781724f5e112ea1acf560cda0a05c7aab8533c87a8a5be4e097fc421ccd6eee

-- Keep knowledge_base_search hidden and independent AIDP search selectable.
UPDATE nexent.ag_tool_info_t
SET is_user_selectable = FALSE
WHERE name = 'knowledge_base_search'
  AND is_user_selectable IS DISTINCT FROM FALSE;

UPDATE nexent.ag_tool_info_t
SET is_user_selectable = TRUE
WHERE name = 'ind_aidp_search'
  AND is_user_selectable IS DISTINCT FROM TRUE;


-- Source migration: v2.7.1_002_chat_source_snapshots.sql
-- Source SHA-256: d5f4de32e812218d00111561f42e49d6ac84727de9a2c6ef9f5ae27cf78ea56c

-- Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

-- Add AIDP-specific retrieval snapshots for each search hit.
ALTER TABLE nexent.conversation_source_search_t
    ADD COLUMN IF NOT EXISTS aidp_metadata JSONB,
    ADD COLUMN IF NOT EXISTS aidp_source_reference JSONB;

COMMENT ON COLUMN nexent.conversation_source_search_t.aidp_metadata
    IS 'Opaque AIDP metadata snapshot returned for this retrieval hit';
COMMENT ON COLUMN nexent.conversation_source_search_t.aidp_source_reference
    IS 'AIDP source reference attributes for this retrieval hit, excluding metadata';


-- Source migration: v2.7.1_002_migrate_chat_menu_to_workbench.sql
-- Source SHA-256: 669f7224fe85dc3e3fc16fcb6608e301154b88c753133326d15af37d653d12da

-- Preserve existing chat menu grants as independent workbench menu grants.
UPDATE nexent.role_permission_t
SET permission_subtype = '/workbench'
WHERE permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype = '/chat';


-- Source migration: v2.7.1_004_workbench_pin_timestamp.sql
-- Source SHA-256: 13a0e4e2dff552fefe641e63fd54c9fdc6ca4b0cb299d91877b0c63fcaed5cec

-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS workbench_pinned_at TIMESTAMP;

COMMENT ON COLUMN nexent.conversation_record_t.workbench_pinned_at IS
    'Personal Workbench pin time as a UTC timestamp; NULL means unpinned; independent of conversation activity';

CREATE INDEX IF NOT EXISTS idx_conversation_workbench_pin_order
    ON nexent.conversation_record_t (created_by, workbench_pinned_at DESC, conversation_id DESC)
    WHERE delete_flag = 'N' AND workbench_pinned_at IS NOT NULL
      AND workbench_config IS NOT NULL AND workbench_config != 'null'::jsonb;


-- Source migration: v2.7.1_005_remove_agent_prompt_templates.sql
-- Source SHA-256: 339d695e3be8246819a5eb6d14620eb6f077bdf68098d9b139c2b99bbeb8344e

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


-- Source migration: v2.7.1_006_remove_legacy_space_permissions.sql
-- Source SHA-256: f5fe48fd4aee529a7eaecb438ac73be17c2274c1a47b117fd1199075693a3921

-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

BEGIN;

-- The evaluation UI now lives at /evaluation; the orphaned /space page is retired.
-- Match semantic grants rather than historical IDs, which vary across deployments.
-- Preserve current evaluation access and non-navigation permissions.
DELETE FROM nexent.role_permission_t
WHERE permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype IN ('/space', '/space/evaluation', '/space/evaluators');

COMMIT;


-- Source migration: v2.7.1_007_conversation_activity_and_source.sql
-- Source SHA-256: e39cd5cec55b34c1e0d7791aadd82809d533580f30d1008d68e070f3013599c5
-- Deliberate simplification: classify only explicit run message references without scanning message units.

-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_message_t
    ADD COLUMN IF NOT EXISTS message_source VARCHAR(16) NOT NULL DEFAULT 'CHAT';
ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS last_activity_time TIMESTAMP;

COMMENT ON COLUMN nexent.conversation_message_t.message_source IS
    'Trusted message origin: CHAT consumes the ordinary user-turn quota; AUTOMATION is exempt';
COMMENT ON COLUMN nexent.conversation_record_t.last_activity_time IS
    'Last committed visible message activity as a UTC timestamp; NULL falls back to conversation creation';

-- Classify explicit run message identities, never an entire task conversation.
UPDATE nexent.conversation_message_t AS m
SET message_source = 'AUTOMATION'
FROM nexent.agent_automation_run_t AS r
CROSS JOIN LATERAL (
    VALUES
        (r.user_message_id),
        (r.assistant_message_id)
) AS v(message_id)
WHERE v.message_id IS NOT NULL
  AND m.conversation_id = r.conversation_id
  AND m.message_id = v.message_id
  AND m.message_source = 'CHAT';

-- Legacy audit timestamps include title/config changes, so use message creation.
UPDATE nexent.conversation_record_t AS conversation
SET last_activity_time = COALESCE(
    (SELECT MAX(message.create_time)
     FROM nexent.conversation_message_t AS message
     WHERE message.conversation_id = conversation.conversation_id
       AND message.delete_flag = 'N'
       AND (message.message_role = 'user'
            OR (message.message_role = 'assistant' AND message.message_content <> ''))),
    conversation.create_time
)
WHERE conversation.last_activity_time IS NULL;

CREATE INDEX IF NOT EXISTS idx_conversation_activity_order
    ON nexent.conversation_record_t
    (created_by, (COALESCE(last_activity_time, create_time)) DESC, conversation_id DESC)
    WHERE delete_flag = 'N';
CREATE INDEX IF NOT EXISTS idx_conversation_chat_turns
    ON nexent.conversation_message_t (conversation_id)
    WHERE delete_flag = 'N' AND message_role = 'user' AND message_source = 'CHAT';


-- Source migration: v2.7.1_008_conversation_title_version.sql
-- Source SHA-256: 44ef8f642fda0ba16414bfeeac6a96674af8ba76aa155d1cd8360b161004ad77

-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS title_version INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN nexent.conversation_record_t.title_version IS
    'Monotonic title revision; every stored rename advances it independently of activity';


-- Source migration: v2.8.0_009_restore_user_model_read.sql

-- Ordinary users consume tenant models in Agent chat and Workbench. Model
-- management writes and navigation remain restricted to their existing roles.
-- Historical permission reseeding omitted this read-only grant.
BEGIN;

-- Serialize the semantic grant check with concurrent permission writers.
LOCK TABLE nexent.role_permission_t IN SHARE ROW EXCLUSIVE MODE;

INSERT INTO nexent.role_permission_t (
    role_permission_id, user_role, permission_category, permission_type, permission_subtype
)
SELECT 143, 'USER', 'RESOURCE', 'MODEL', 'READ'
WHERE NOT EXISTS (
    SELECT 1
    FROM nexent.role_permission_t
    WHERE user_role = 'USER'
      AND permission_category = 'RESOURCE'
      AND permission_type = 'MODEL'
      AND permission_subtype = 'READ'
);

COMMIT;
