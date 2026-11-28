-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Nexent merged SQL migrations: v2.9.0
-- Previous release tag: v2.8.5
-- Source bodies are embedded in deployment order, byte-for-byte except for
-- each source file's leading copyright line, which appears once above.
-- Do not reorder or rewrite sections without equivalence validation.

-- Source migration: v2.8.0_001_a2a_ssl_verify.sql
-- Source SHA-256: 2ddf1be0c0aa25dccebe417a261a7d3b059198b4729659385f3859b46e17227c
ALTER TABLE nexent.ag_a2a_external_agent_t
    ADD COLUMN IF NOT EXISTS ssl_verify BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.ssl_verify IS
    'Verify peer TLS certificates for Agent Card retrieval and A2A invocation';

-- Source migration: v2.8.0_aidp_fixed_retrieval_policy.sql
-- Source SHA-256: 539333be0fbb3300ef065a59c0c88e286ea6c147f2138c444d3e74e877ef4119
--
-- Fixed-value AIDP retrieval policy upgrade.
--
-- Historical AIDP tool definitions (released <= 2.7.0) predate the graph and
-- candidate fields. This migration:
--   1. replaces the nine matching parameter definitions with canonical metadata
--      on every AIDP catalog row, preserving tool_id and unrelated parameters;
--   2. materializes fixed candidate/boolean values on every AIDP tool instance
--      version, including soft-deleted rows, without overwriting explicit
--      values, and normalizes legacy integer representations and hybrid_search.
-- Conversation and Workbench scopes no longer contain retrieval parameters.
--
-- The migration is idempotent and must not be edited after release.

WITH new_defs AS (
    SELECT '[
      {"type":"integer","name":"vector_candidates","description":"Vector candidates","description_zh":"向量初步检索条数；固定整数，1–500","default":10,"optional":true,"constraints":{"ge":1,"le":500}},
      {"type":"integer","name":"full_text_candidates","description":"Full-text candidates","description_zh":"全文初步检索条数；固定整数，1–500","default":10,"optional":true,"constraints":{"ge":1,"le":500}},
      {"type":"integer","name":"hybrid_top_k","description":"Vector/full-text cap; zero means no separate cap, still bounded by top_k","description_zh":"向量／全文部分返回上限；0 表示不单独限制，最终仍受总返回上限约束","default":0,"optional":true,"constraints":{"ge":0,"le":100}},
      {"type":"integer","name":"graph_top_k","description":"Graph cap; zero means no separate cap, still bounded by top_k","description_zh":"图谱返回上限；0 表示不单独限制，最终仍受总返回上限约束","default":0,"optional":true,"constraints":{"ge":0,"le":100}},
      {"type":"float","name":"vector_score_threshold","description":"Vector threshold","description_zh":"向量检索分数阈值，范围 0–1","default":0.0,"optional":true,"constraints":{"ge":0.0,"le":1.0}},
      {"type":"float","name":"full_text_score_threshold","description":"Full-text threshold","description_zh":"全文检索分数阈值，范围 0–1","default":0.0,"optional":true,"constraints":{"ge":0.0,"le":1.0}},
      {"type":"float","name":"graph_score_threshold","description":"Graph threshold","description_zh":"图谱检索分数阈值，范围 0–1","default":0.0,"optional":true,"constraints":{"ge":0.0,"le":1.0}},
      {"type":"boolean","name":"graph_reranking_enable","description":"Include graph results in unified reranking","description_zh":"图谱是否参与统一重排；固定布尔值","default":true,"optional":true},
      {"type":"boolean","name":"query_expansion_enable","description":"Enable query expansion","description_zh":"是否启用查询扩展","default":false,"optional":true}
    ]'::jsonb AS defs
),
aidp_definitions AS (
    SELECT t.tool_id,
           COALESCE(
               (
                   SELECT jsonb_agg(elem ORDER BY ord)
                   FROM jsonb_array_elements(COALESCE(t.params::jsonb, '[]'::jsonb))
                        WITH ORDINALITY AS e(elem, ord)
                   WHERE elem->>'name' NOT IN (
                       SELECT value->>'name' FROM jsonb_array_elements(nd.defs)
                   )
               ),
               '[]'::jsonb
           ) || nd.defs AS new_params
    FROM nexent.ag_tool_info_t AS t
    CROSS JOIN new_defs AS nd
    WHERE t.class_name IN ('AidpSearchTool', 'IndependentAidpSearchTool')
       OR t.name IN ('aidp_search', 'ind_aidp_search')
)
UPDATE nexent.ag_tool_info_t AS t
SET params = d.new_params::json
FROM aidp_definitions AS d
WHERE t.tool_id = d.tool_id
  AND t.params::jsonb IS DISTINCT FROM d.new_params;

WITH aidp_instances AS (
    SELECT i.tool_instance_id, i.version_no, i.params::jsonb AS params,
           CASE WHEN jsonb_typeof(i.params::jsonb->'top_k') IN ('number', 'string')
                THEN (i.params::jsonb->>'top_k')::numeric::int END AS normalized_top_k
    FROM nexent.ag_tool_instance_t AS i
    JOIN nexent.ag_tool_info_t AS ti ON ti.tool_id = i.tool_id
    WHERE ti.class_name IN ('AidpSearchTool', 'IndependentAidpSearchTool')
       OR ti.name IN ('aidp_search', 'ind_aidp_search')
),
fixed_instances AS (
    SELECT tool_instance_id, version_no,
           jsonb_build_object(
               'vector_candidates',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'vector_candidates') = 'number'
                             THEN (params->>'vector_candidates')::numeric::int END,
                        normalized_top_k,
                       10
                   ),
               'full_text_candidates',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'full_text_candidates') = 'number'
                             THEN (params->>'full_text_candidates')::numeric::int END,
                        normalized_top_k,
                       10
                   ),
               'hybrid_top_k',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'hybrid_top_k') = 'number'
                             THEN (params->>'hybrid_top_k')::numeric::int END,
                       0
                   ),
               'graph_top_k',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'graph_top_k') = 'number'
                             THEN (params->>'graph_top_k')::numeric::int END,
                       0
                   ),
               'vector_score_threshold',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'vector_score_threshold') = 'number'
                            THEN (params->>'vector_score_threshold')::numeric END,
                       0.0
                   ),
               'full_text_score_threshold',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'full_text_score_threshold') = 'number'
                            THEN (params->>'full_text_score_threshold')::numeric END,
                       0.0
                   ),
               'graph_score_threshold',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'graph_score_threshold') = 'number'
                            THEN (params->>'graph_score_threshold')::numeric END,
                       0.0
                   ),
               'graph_reranking_enable',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'graph_reranking_enable') = 'boolean'
                            THEN (params->>'graph_reranking_enable')::boolean END,
                       CASE WHEN jsonb_typeof(params->'reranking_enable') = 'boolean'
                            THEN (params->>'reranking_enable')::boolean END,
                       true
                   ),
               'query_expansion_enable',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'query_expansion_enable') = 'boolean'
                            THEN (params->>'query_expansion_enable')::boolean END,
                       false
                   ),
               'search_method',
                   CASE WHEN params->>'search_method' = 'hybrid_search'
                        THEN 'vector_search|full_text_search|graph_search'
                        ELSE COALESCE(params->>'search_method',
                                      'vector_search|full_text_search|graph_search')
                   END
           ) || (params - ARRAY[
               'vector_candidates', 'full_text_candidates', 'hybrid_top_k',
               'graph_top_k', 'vector_score_threshold', 'full_text_score_threshold',
               'graph_score_threshold', 'graph_reranking_enable',
               'query_expansion_enable', 'search_method'
            ]) || CASE WHEN normalized_top_k IS NOT NULL
                       THEN jsonb_build_object('top_k', normalized_top_k)
                       ELSE '{}'::jsonb END AS new_params
    FROM aidp_instances
)
UPDATE nexent.ag_tool_instance_t AS i
SET params = f.new_params::json
FROM fixed_instances AS f
WHERE i.tool_instance_id = f.tool_instance_id
  AND i.version_no = f.version_no
  AND i.params::jsonb IS DISTINCT FROM f.new_params;

-- Source migration: v2.8.3_001_fix_agent_ingroup_permission.sql
-- Source SHA-256: 89a0e490748f6c021e5619618de1fb76c9077e744506c4632fb1b3592bfa3dcc

-- Normalize legacy agent in-group permission values left by the pre-redesign
-- deployment form. The classic form saved "EDITABLE" for the "editable" option,
-- while backend draft-edit authorization (require_agent_draft_edit) only
-- accepts the exact value "EDIT". Agents saved through the legacy form stayed
-- read-only for non-creator, non-admin users even though the UI showed them
-- as editable, and removing/configuring tools on such agents failed with
-- agent_read_only. Align the stored value with the canonical enum so existing
-- agents match what the UI intended.
--
-- Scope notes:
--   - Case variants (e.g. "editable") are covered via UPPER().
--   - NULL is intentionally untouched: it means "not configured" and resolves
--     to READ_ONLY by design.
--   - "INHERIT" is intentionally untouched: its inheritance semantics for
--     draft-edit are a separate product decision.
--   - Idempotent: re-running matches no rows. Safe under the migration
--     runner's reapply-on-checksum-change behavior.

UPDATE nexent.ag_tenant_agent_t
SET ingroup_permission = 'EDIT'
WHERE UPPER(ingroup_permission) = 'EDITABLE';

-- Source migration: v2.9.0_001_local_user_accounts.sql
-- Source SHA-256: 0769d1ecc7aa2e3b5d36cc48e9b81f4d567d17168794e097ce6e3fe60609edf7
-- Final account schema; the host importer owns the historical credential transaction.
DO $account_upgrade$
DECLARE
    old_role boolean;
    old_email boolean;
    role_expr text;
    email_expr text;
    row_data record;
    conflict_ids json;
    system_speed boolean;
    api_only boolean;
    provider_bound boolean;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('account-writers'));
    CREATE TABLE IF NOT EXISTS nexent.user_account_t (
        account_id SERIAL PRIMARY KEY,
        user_id VARCHAR(100) NOT NULL,
        user_email VARCHAR(255),
        user_role VARCHAR(30),
        password_hash VARCHAR(512),
        password_hash_scheme VARCHAR(30),
        password_login_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        token_version INTEGER NOT NULL DEFAULT 0,
        email_confirmed_at TIMESTAMP,
        source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by VARCHAR(100),
        create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_by VARCHAR(100),
        update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
    );
    -- Read old availability only when present; never recreate the retired column.
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent'
               AND table_name='user_account_t' AND column_name='account_status') THEN
        UPDATE nexent.user_account_t SET delete_flag='Y',update_time=CURRENT_TIMESTAMP,
            updated_by='account-availability-migration'
        WHERE account_status<>'active' AND delete_flag='N';
        ALTER TABLE nexent.user_account_t DROP COLUMN account_status;
    END IF;
    UPDATE nexent.user_account_t SET source_metadata=source_metadata-'credential_migration_pending',
        update_time=CURRENT_TIMESTAMP,updated_by='account-availability-migration'
    WHERE source_metadata ? 'credential_migration_pending';
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='email') THEN
        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='user_email') THEN
            SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids FROM nexent.user_account_t
            WHERE email IS NOT NULL AND user_email IS NOT NULL AND lower(trim(email))<>lower(trim(user_email));
            IF conflict_ids IS NOT NULL THEN RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids; END IF;
            UPDATE nexent.user_account_t SET user_email=email WHERE user_email IS NULL;
            ALTER TABLE nexent.user_account_t DROP COLUMN email;
        ELSE
            ALTER TABLE nexent.user_account_t RENAME COLUMN email TO user_email;
        END IF;
    END IF;
    ALTER TABLE nexent.user_account_t ADD COLUMN IF NOT EXISTS user_email VARCHAR(255);
    ALTER TABLE nexent.user_account_t ADD COLUMN IF NOT EXISTS user_role VARCHAR(30);
    ALTER TABLE nexent.user_account_t ALTER COLUMN user_email DROP NOT NULL;
    SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids FROM (
        SELECT user_id FROM nexent.user_account_t GROUP BY user_id HAVING count(*)>1
    ) duplicate_ids;
    IF conflict_ids IS NOT NULL THEN RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids; END IF;

    -- Profiles survive only for this transaction, including the subsequent host import.
    CREATE TEMP TABLE IF NOT EXISTS account_migration_profiles (
        user_id VARCHAR(100), role_value VARCHAR(30), email_value VARCHAR(255),
        roles INTEGER, emails INTEGER
    ) ON COMMIT DROP;
    TRUNCATE pg_temp.account_migration_profiles;
    IF to_regclass('nexent.user_tenant_t') IS NOT NULL THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_tenant_t' AND column_name='user_role') INTO old_role;
        SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_tenant_t' AND column_name='user_email') INTO old_email;
        IF old_role OR old_email THEN
            role_expr := CASE WHEN old_role THEN 'nullif(upper(trim(user_role)), '''')' ELSE 'NULL::varchar' END;
            email_expr := CASE WHEN old_email THEN 'nullif(lower(trim(user_email)), '''')' ELSE 'NULL::varchar' END;
            EXECUTE format('INSERT INTO pg_temp.account_migration_profiles SELECT user_id,min(%1$s),min(%2$s),count(DISTINCT %1$s),count(DISTINCT %2$s) FROM nexent.user_tenant_t WHERE delete_flag=''N'' GROUP BY user_id',role_expr,email_expr);
            SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids
            FROM pg_temp.account_migration_profiles WHERE roles>1 OR emails>1;
            IF conflict_ids IS NOT NULL THEN RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids; END IF;
            FOR row_data IN SELECT * FROM pg_temp.account_migration_profiles LOOP
                IF EXISTS (SELECT 1 FROM nexent.user_account_t WHERE user_id=row_data.user_id) THEN
                    IF EXISTS (SELECT 1 FROM nexent.user_account_t WHERE user_id=row_data.user_id
                               AND delete_flag='N' AND user_email IS NOT NULL AND row_data.email_value IS NOT NULL
                               AND lower(trim(user_email))<>row_data.email_value) THEN
                        RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',json_build_array(row_data.user_id);
                    END IF;
                    UPDATE nexent.user_account_t SET
                        user_email=coalesce(user_email,row_data.email_value),
                        user_role=coalesce(user_role,row_data.role_value),
                        updated_by='account-schema-migration',update_time=CURRENT_TIMESTAMP
                    WHERE user_id=row_data.user_id AND delete_flag='N'
                      AND ((user_email IS NULL AND row_data.email_value IS NOT NULL)
                        OR (user_role IS NULL AND row_data.role_value IS NOT NULL));
                    CONTINUE;
                END IF;
                system_speed := false;
                api_only := false;
                provider_bound := false;
                IF row_data.user_id='user_id' AND row_data.role_value='SPEED' AND row_data.email_value IS NULL THEN
                    SELECT EXISTS (SELECT 1 FROM nexent.user_tenant_t WHERE user_id=row_data.user_id AND tenant_id='tenant_id' AND delete_flag='N')
                       AND NOT EXISTS (SELECT 1 FROM nexent.user_tenant_t WHERE user_id=row_data.user_id AND delete_flag='N' AND tenant_id IS DISTINCT FROM 'tenant_id') INTO system_speed;
                END IF;
                IF row_data.email_value IS NULL AND row_data.role_value IN ('USER','DEV')
                   AND to_regclass('nexent.user_token_info_t') IS NOT NULL THEN
                    SELECT EXISTS (SELECT 1 FROM nexent.user_token_info_t WHERE user_id=row_data.user_id) INTO api_only;
                END IF;
                IF row_data.role_value IS NOT NULL AND row_data.email_value IS NOT NULL
                   AND to_regclass('nexent.user_oauth_account_t') IS NOT NULL THEN
                    SELECT EXISTS (SELECT 1 FROM nexent.user_oauth_account_t
                                   WHERE user_id=row_data.user_id AND delete_flag='N') INTO provider_bound;
                END IF;
                IF system_speed OR api_only OR provider_bound THEN
                    INSERT INTO nexent.user_account_t
                        (user_id,user_email,user_role,password_login_enabled,source_metadata,created_by,updated_by,delete_flag)
                    VALUES (row_data.user_id,row_data.email_value,row_data.role_value,false,
                        CASE WHEN system_speed THEN '{"system_identity":"speed"}'::jsonb
                             WHEN api_only THEN '{"api_only":true}'::jsonb ELSE '{}'::jsonb END,
                        'account-schema-migration','account-schema-migration',CASE WHEN system_speed THEN 'Y' ELSE 'N' END);
                END IF;
            END LOOP;
        END IF;
        ALTER TABLE nexent.user_tenant_t DROP COLUMN IF EXISTS user_role;
        ALTER TABLE nexent.user_tenant_t DROP COLUMN IF EXISTS user_email;
    END IF;
    -- Cross-user email validation belongs after final source eligibility is known.
    -- The importer defers this check until credentials have been classified.
    IF current_setting('nexent.account_import',true) IS DISTINCT FROM 'on' THEN
        SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids FROM nexent.user_account_t
        WHERE delete_flag='N' AND lower(trim(user_email)) IN (
            SELECT lower(trim(user_email)) FROM nexent.user_account_t WHERE delete_flag='N' AND user_email IS NOT NULL
            GROUP BY lower(trim(user_email)) HAVING count(*)>1);
        IF conflict_ids IS NOT NULL THEN RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids; END IF;
    END IF;
    CREATE INDEX IF NOT EXISTS ix_user_account_user_id ON nexent.user_account_t (user_id);
    CREATE INDEX IF NOT EXISTS ix_user_account_email ON nexent.user_account_t (user_email);
    COMMENT ON COLUMN nexent.user_account_t.account_id IS 'Technical account record identifier';
    COMMENT ON COLUMN nexent.user_account_t.user_id IS 'Stable user identifier, including legacy system IDs; account service serializes identity uniqueness';
    COMMENT ON COLUMN nexent.user_account_t.user_email IS 'Normalized lowercase login email; null for passwordless identities';
    COMMENT ON COLUMN nexent.user_account_t.user_role IS 'Canonical account role transferred from original membership data';
    COMMENT ON COLUMN nexent.user_account_t.password_hash IS 'Encoded password hash; never exposed by user APIs';
    COMMENT ON COLUMN nexent.user_account_t.password_hash_scheme IS 'Hash scheme: scrypt or imported bcrypt';
    COMMENT ON COLUMN nexent.user_account_t.password_login_enabled IS 'Whether password authentication is permitted';
    COMMENT ON COLUMN nexent.user_account_t.token_version IS 'Credential revision invalidating earlier JWTs';
    COMMENT ON COLUMN nexent.user_account_t.email_confirmed_at IS 'UTC email confirmation time; null if unconfirmed';
    COMMENT ON COLUMN nexent.user_account_t.source_metadata IS 'Migration/provider provenance, API-only and system identity markers; never grants permissions';
    COMMENT ON COLUMN nexent.user_account_t.created_by IS 'Creating user or migration actor';
    COMMENT ON COLUMN nexent.user_account_t.create_time IS 'UTC creation time';
    COMMENT ON COLUMN nexent.user_account_t.updated_by IS 'Last updating user or system actor';
    COMMENT ON COLUMN nexent.user_account_t.update_time IS 'UTC last update time';
    COMMENT ON COLUMN nexent.user_account_t.delete_flag IS 'Account availability: N enabled, Y disabled or deleted';
END
$account_upgrade$;

-- Source migration: v2.9.0_001_shared_system_agents.sql
-- Source SHA-256: bd35acc99fc8cb1b282f2fa9cdc5f5594f766e57486337dde92d9c042caf12a3
-- Equal-numbered tenant system definitions are identical in the source deployment.
-- Stop old application writers before running this one-shot data migration.
-- The DO statement commits data and its durable completion marker atomically.
DO $migration$
DECLARE
    owner_id CONSTANT text := 'asset_owner_tenant_id';
    marker_id CONSTANT text := '__once_shared_system_agents_v1';
    key_name text;
    canonical_id integer;
    target_id integer;
    old_resource_id integer;
    normalized_name text;
    tool_row nexent.ag_tool_info_t%ROWTYPE;
    skill_row nexent.ag_skill_info_t%ROWTYPE;
    reference_column record;
    trigger_row record;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('system-agent-release:workbench_main'));
    IF EXISTS (SELECT 1 FROM nexent.schema_migrations WHERE migration_id = marker_id) THEN
        RETURN;
    END IF;

    CREATE TEMP TABLE _sa_ids (
        old_id integer PRIMARY KEY, shared_id integer NOT NULL, system_key text NOT NULL
    ) ON COMMIT DROP;
    FOR key_name IN SELECT DISTINCT system_key FROM nexent.ag_tenant_agent_t
        WHERE agent_origin = 'SYSTEM' AND system_key = 'workbench_main'
    LOOP
        SELECT agent_id INTO canonical_id FROM nexent.ag_tenant_agent_t
        WHERE agent_origin = 'SYSTEM' AND system_key = key_name AND version_no = 0
        ORDER BY (tenant_id = owner_id) DESC, (delete_flag = 'N') DESC, agent_id LIMIT 1;
        IF canonical_id IS NULL THEN
            RAISE EXCEPTION 'System Agent % has snapshots but no draft', key_name;
        END IF;
        INSERT INTO _sa_ids SELECT DISTINCT agent_id, canonical_id, key_name
        FROM nexent.ag_tenant_agent_t WHERE agent_origin = 'SYSTEM' AND system_key = key_name;
    END LOOP;

    CREATE TEMP TABLE _sa_agents ON COMMIT DROP AS
    SELECT DISTINCT ON (a.system_key, a.version_no) a.*
    FROM nexent.ag_tenant_agent_t a JOIN _sa_ids m ON m.old_id = a.agent_id
    ORDER BY a.system_key, a.version_no, (a.delete_flag = 'N') DESC,
        (a.agent_id = m.shared_id) DESC, a.agent_id;
    CREATE TEMP TABLE _sa_tools ON COMMIT DROP AS
    SELECT b.* FROM nexent.ag_tool_instance_t b JOIN _sa_agents a
        ON a.agent_id = b.agent_id AND a.version_no = b.version_no
    WHERE a.system_key = 'workbench_main';
    CREATE TEMP TABLE _sa_skills ON COMMIT DROP AS
    SELECT b.* FROM nexent.ag_skill_instance_t b JOIN _sa_agents a
        ON a.agent_id = b.agent_id AND a.version_no = b.version_no
    WHERE a.system_key = 'workbench_main';
    CREATE TEMP TABLE _sa_relations ON COMMIT DROP AS
    SELECT b.* FROM nexent.ag_agent_relation_t b JOIN _sa_agents a
        ON a.agent_id = b.parent_agent_id AND a.version_no = b.version_no
    WHERE a.system_key = 'workbench_main';
    CREATE TEMP TABLE _sa_versions ON COMMIT DROP AS
    SELECT DISTINCT ON (m.system_key, v.version_no) v.*
    FROM nexent.ag_tenant_agent_version_t v JOIN _sa_ids m ON m.old_id = v.agent_id
    WHERE m.system_key = 'workbench_main'
    ORDER BY m.system_key, v.version_no, (v.agent_id = m.shared_id) DESC, v.id;
    CREATE TEMP TABLE _sa_tool_map (old_id integer PRIMARY KEY, shared_id integer NOT NULL) ON COMMIT DROP;
    CREATE TEMP TABLE _sa_skill_map (old_id integer PRIMARY KEY, shared_id integer NOT NULL) ON COMMIT DROP;

    -- Clone tenant definitions into the shared catalog; ordinary tenant resources stay intact.
    FOR old_resource_id IN
        SELECT tool_id FROM _sa_tools
        UNION SELECT r.tool_id FROM nexent.ag_skill_tools_rel_t r
            JOIN _sa_skills s ON s.skill_id = r.skill_id
    LOOP
        SELECT * INTO STRICT tool_row FROM nexent.ag_tool_info_t WHERE tool_id = old_resource_id;
        IF tool_row.author = owner_id THEN
            target_id := old_resource_id;
        ELSE
            IF tool_row.source IS DISTINCT FROM 'local' THEN
                RAISE EXCEPTION 'Cannot share tenant MCP tool %', old_resource_id;
            END IF;
            SELECT tool_id INTO target_id FROM nexent.ag_tool_info_t
            WHERE author = owner_id AND source = 'local' AND name = tool_row.name
                AND class_name IS NOT DISTINCT FROM tool_row.class_name AND delete_flag = 'N'
            ORDER BY tool_id LIMIT 1;
            IF target_id IS NULL THEN
                tool_row.tool_id := nextval('nexent.ag_tool_info_t_tool_id_seq');
                tool_row.author := owner_id;
                INSERT INTO nexent.ag_tool_info_t SELECT (tool_row).*;
                target_id := tool_row.tool_id;
            END IF;
        END IF;
        INSERT INTO _sa_tool_map VALUES (old_resource_id, target_id);
    END LOOP;
    FOR old_resource_id IN SELECT DISTINCT skill_id FROM _sa_skills
    LOOP
        SELECT * INTO STRICT skill_row FROM nexent.ag_skill_info_t WHERE skill_id = old_resource_id;
        IF skill_row.tenant_id = owner_id THEN
            target_id := old_resource_id;
        ELSE
            IF lower(skill_row.source) IS DISTINCT FROM 'official' THEN
                RAISE EXCEPTION 'Cannot share non-official Workbench Skill %', old_resource_id;
            END IF;
            normalized_name := regexp_replace(skill_row.skill_name, '_[0-9]+$', '');
            SELECT skill_id INTO target_id FROM nexent.ag_skill_info_t
            WHERE tenant_id = owner_id AND skill_name = normalized_name
                AND source = 'official' AND delete_flag = 'N' ORDER BY skill_id LIMIT 1;
            IF target_id IS NULL THEN
                skill_row.skill_id := nextval('nexent.ag_skill_info_t_skill_id_seq');
                skill_row.tenant_id := owner_id;
                skill_row.skill_name := normalized_name;
                INSERT INTO nexent.ag_skill_info_t SELECT (skill_row).*;
                target_id := skill_row.skill_id;
            END IF;
        END IF;
        INSERT INTO _sa_skill_map VALUES (old_resource_id, target_id);
    END LOOP;
    INSERT INTO nexent.ag_skill_tools_rel_t (rel_id, skill_id, tool_id, created_by, updated_by, delete_flag)
    SELECT nextval('nexent.ag_skill_tools_rel_t_rel_id_seq'), skill_id, tool_id, 'system', 'system', 'N'
    FROM (
        SELECT DISTINCT s.shared_id AS skill_id, t.shared_id AS tool_id
        FROM nexent.ag_skill_tools_rel_t r JOIN _sa_skill_map s ON s.old_id = r.skill_id
        JOIN _sa_tool_map t ON t.old_id = r.tool_id WHERE r.delete_flag = 'N'
        EXCEPT SELECT skill_id, tool_id FROM nexent.ag_skill_tools_rel_t WHERE delete_flag = 'N'
    ) dependencies;

    UPDATE _sa_tools b SET tool_id = m.shared_id FROM _sa_tool_map m WHERE m.old_id = b.tool_id;
    UPDATE _sa_skills b SET skill_id = m.shared_id FROM _sa_skill_map m WHERE m.old_id = b.skill_id;
    UPDATE _sa_tools b SET agent_id = m.shared_id, tenant_id = owner_id FROM _sa_ids m WHERE m.old_id = b.agent_id;
    UPDATE _sa_skills b SET agent_id = m.shared_id, tenant_id = owner_id FROM _sa_ids m WHERE m.old_id = b.agent_id;
    UPDATE _sa_relations b SET parent_agent_id = m.shared_id, tenant_id = owner_id FROM _sa_ids m WHERE m.old_id = b.parent_agent_id;
    UPDATE _sa_relations b SET selected_agent_id = m.shared_id FROM _sa_ids m WHERE m.old_id = b.selected_agent_id;
    IF EXISTS (SELECT 1 FROM _sa_relations r WHERE NOT EXISTS (
        SELECT 1 FROM nexent.ag_tenant_agent_t a WHERE a.agent_id = r.selected_agent_id
            AND (a.tenant_id = owner_id OR a.agent_id IN (SELECT shared_id FROM _sa_ids))
    )) THEN
        RAISE EXCEPTION 'Workbench cannot share a tenant-owned child Agent';
    END IF;
    UPDATE _sa_versions v SET agent_id = m.shared_id, tenant_id = owner_id FROM _sa_ids m WHERE m.old_id = v.agent_id;
    -- Force the first shared publication even when a legacy revision equals APP_VERSION.
    UPDATE _sa_agents SET system_revision = NULL WHERE version_no = 0 AND system_key = 'workbench_main'
        AND (tenant_id IS DISTINCT FROM owner_id OR (SELECT count(DISTINCT old_id) FROM _sa_ids WHERE system_key = 'workbench_main') > 1);
    UPDATE _sa_agents a SET agent_id = m.shared_id, tenant_id = owner_id FROM _sa_ids m WHERE m.old_id = a.agent_id;
    UPDATE _sa_agents a SET parent_agent_id = m.shared_id FROM _sa_ids m WHERE m.old_id = a.parent_agent_id;
    UPDATE _sa_agents SET delete_flag = 'N' WHERE version_no = 0;

    DELETE FROM nexent.ag_tool_instance_t WHERE agent_id IN (SELECT old_id FROM _sa_ids);
    DELETE FROM nexent.ag_skill_instance_t WHERE agent_id IN (SELECT old_id FROM _sa_ids);
    DELETE FROM nexent.ag_agent_relation_t WHERE parent_agent_id IN (SELECT old_id FROM _sa_ids);
    DELETE FROM nexent.ag_tenant_agent_version_t WHERE agent_id IN (SELECT old_id FROM _sa_ids);

    -- Preserve audit timestamps even on tables with automatic UPDATE triggers.
    CREATE TEMP TABLE _sa_triggers ON COMMIT DROP AS
    SELECT c.relname AS table_name, t.tgname, t.tgenabled FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'nexent' AND NOT t.tgisinternal AND t.tgenabled <> 'D'
        AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
            AND a.attname IN ('agent_id', 'parent_agent_id', 'selected_agent_id', 'local_agent_id') AND NOT a.attisdropped);
    FOR trigger_row IN SELECT * FROM _sa_triggers LOOP
        EXECUTE format('ALTER TABLE nexent.%I DISABLE TRIGGER %I', trigger_row.table_name, trigger_row.tgname);
    END LOOP;
    FOR reference_column IN
        SELECT c.table_name, c.column_name, c.data_type FROM information_schema.columns c
        WHERE c.table_schema = 'nexent' AND c.column_name IN ('agent_id', 'parent_agent_id', 'selected_agent_id', 'local_agent_id')
            AND c.table_name NOT IN ('ag_tool_instance_t', 'ag_skill_instance_t', 'ag_tenant_agent_version_t')
            AND NOT (c.table_name = 'ag_tenant_agent_t' AND c.column_name = 'agent_id')
            AND EXISTS (SELECT 1 FROM information_schema.tables t WHERE t.table_schema = c.table_schema
                AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE')
    LOOP
        IF reference_column.data_type IN ('text', 'character varying', 'character') THEN
            EXECUTE format('UPDATE nexent.%I r SET %I = m.shared_id::text FROM _sa_ids m WHERE r.%I = m.old_id::text AND m.old_id <> m.shared_id',
                reference_column.table_name, reference_column.column_name, reference_column.column_name);
        ELSE
            EXECUTE format('UPDATE nexent.%I r SET %I = m.shared_id FROM _sa_ids m WHERE r.%I = m.old_id AND m.old_id <> m.shared_id',
                reference_column.table_name, reference_column.column_name, reference_column.column_name);
        END IF;
    END LOOP;
    FOR trigger_row IN SELECT * FROM _sa_triggers LOOP
        EXECUTE format('ALTER TABLE nexent.%I ENABLE %s TRIGGER %I', trigger_row.table_name,
            CASE trigger_row.tgenabled WHEN 'A' THEN 'ALWAYS' WHEN 'R' THEN 'REPLICA' ELSE '' END, trigger_row.tgname);
    END LOOP;
    DELETE FROM nexent.ag_tenant_agent_t WHERE agent_id IN (SELECT old_id FROM _sa_ids);
    INSERT INTO nexent.ag_tenant_agent_t SELECT * FROM _sa_agents;
    INSERT INTO nexent.ag_tenant_agent_version_t SELECT * FROM _sa_versions;
    INSERT INTO nexent.ag_tool_instance_t SELECT * FROM _sa_tools;
    INSERT INTO nexent.ag_skill_instance_t SELECT * FROM _sa_skills;
    INSERT INTO nexent.ag_agent_relation_t SELECT * FROM _sa_relations;

    INSERT INTO nexent.schema_migrations (migration_id, checksum, status, source_file)
    VALUES (marker_id, 'one-shot-v1', 'applied', 'v2.9.0_001_shared_system_agents.sql');
END;
$migration$;

-- Source migration: v2.9.0_002_conversation_projection_receipt.sql
-- Source SHA-256: a04a8766240a341a631eb1a4c5b94187fb940fd743aab921e688ca094ee13d35

CREATE TABLE IF NOT EXISTS nexent.conversation_projection_receipt_t (
    run_id VARCHAR(32) PRIMARY KEY,
    message_id INTEGER NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    payload_sha256 VARCHAR(64) NOT NULL,
    unit_ids JSONB NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100) NOT NULL,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS idx_conversation_projection_receipt_message
    ON nexent.conversation_projection_receipt_t (message_id);

COMMENT ON TABLE nexent.conversation_projection_receipt_t IS 'Committed assistant projection receipts used for AgentOS replay.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.run_id IS 'Server-issued AgentOS run identifier for one committed projection.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.message_id IS 'Assistant message bound by the conversation finalization transaction.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.tenant_id IS 'Tenant of the authorized projection actor.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.payload_sha256 IS 'Versioned SHA-256 digest of the submitted projection payload.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.unit_ids IS 'Object mapping persisted unit indexes to their integer unit IDs.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.created_by IS 'User who owns and submitted the assistant projection.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.create_time IS 'Time the projection receipt was created.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.updated_by IS 'User recorded when writing the immutable receipt.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.update_time IS 'Time the immutable receipt was recorded.';
COMMENT ON COLUMN nexent.conversation_projection_receipt_t.delete_flag IS 'Soft-delete marker; regular replay only reads active receipts.';

-- Source migration: v2.9.0_002_shared_creator_identities.sql
-- Source SHA-256: cffd05fa2f86c518e101d92e82a4df4f9ddfe11659e2f335093007ad7b87f7a3
-- Initialize public code-backed creators on both fresh installations and upgrades.
-- Prompts, tools and Skill resources remain in product code/files, not Agent snapshots.
DO $migration$
DECLARE
    marker_id CONSTANT text := '__once_shared_creator_identities_v1';
    owner_id CONSTANT text := 'asset_owner_tenant_id';
    kind text;
    creator_id integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('system-agent-release:nl2agent_main'));
    PERFORM pg_advisory_xact_lock(hashtext('system-agent-release:nl2skill_main'));
    IF EXISTS (SELECT 1 FROM nexent.schema_migrations WHERE migration_id = marker_id) THEN
        RETURN;
    END IF;
    CREATE UNIQUE INDEX IF NOT EXISTS uq_public_creator_identity
        ON nexent.ag_tenant_agent_t (system_key)
        WHERE tenant_id = 'asset_owner_tenant_id' AND agent_origin = 'SYSTEM'
            AND version_no = 0 AND delete_flag = 'N'
            AND system_key IN ('nl2agent_main', 'nl2skill_main');
    FOREACH kind IN ARRAY ARRAY['agent', 'skill'] LOOP
        SELECT agent_id INTO creator_id FROM nexent.ag_tenant_agent_t
        WHERE tenant_id = owner_id AND agent_origin = 'SYSTEM'
            AND system_key = 'nl2' || kind || '_main' AND version_no = 0 AND delete_flag = 'N';
        IF creator_id IS NULL THEN
            INSERT INTO nexent.ag_tenant_agent_t
                (agent_id, tenant_id, agent_origin, system_key, name, display_name,
                 description, version_no, enabled, max_steps, model_ids, group_ids,
                 ingroup_permission, is_main_agent, is_a2a, enable_context_manager,
                 enable_protocol_repair_retry, is_new, created_by, updated_by, delete_flag)
            VALUES (nextval('nexent.ag_tenant_agent_t_agent_id_seq'), owner_id, 'SYSTEM',
                'nl2' || kind || '_main', 'nl2' || kind || '_main',
                CASE kind WHEN 'agent' THEN 'NL2Agent' ELSE 'NL2Skill' END,
                'Natural-language creator', 0, true,
                CASE kind WHEN 'agent' THEN 8 ELSE 5 END, ARRAY[]::integer[], '',
                'PRIVATE', true, false, true, true, false, 'system', 'system', 'N');
        END IF;
    END LOOP;
    INSERT INTO nexent.schema_migrations (migration_id, checksum, status, source_file)
    VALUES (marker_id, 'one-shot-v1', 'applied', 'v2.9.0_002_shared_creator_identities.sql');
END;
$migration$;

-- Source migration: v2.9.0_003_conversation_run_admission.sql
-- Source SHA-256: 30f5935e4f73393029250d89fb1b330d7702511301539a25e19d3faa15e61d93

CREATE TABLE IF NOT EXISTS nexent.conversation_run_admission_t (
    scope_sha256 VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    run_id VARCHAR(32) NOT NULL,
    request_sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    conversation_id INTEGER,
    journal_available BOOLEAN NOT NULL DEFAULT FALSE,
    created_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100) NOT NULL,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);

COMMENT ON TABLE nexent.conversation_run_admission_t IS 'Durable conversation run submissions keyed by actor scope and idempotency key.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.scope_sha256 IS 'Digest of the tenant, authenticated user and client idempotency key.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.tenant_id IS 'Tenant that owns the submission.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.run_id IS 'Server-generated run identifier returned on retries.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.request_sha256 IS 'Digest of the normalized signed execution request.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.status IS 'Submission outcome: pending, admitted or rejected.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.conversation_id IS 'Owned conversation bound before starting the stream producer.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.journal_available IS 'Whether the run opened its Redis output journal at admission.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.created_by IS 'User who submitted the request.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.create_time IS 'Time of the first successful claim.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.updated_by IS 'User recorded when the admission outcome changed.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.update_time IS 'Time of the most recent admission change.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.delete_flag IS 'Soft-delete marker; a removed claim is never reassigned.';

-- Source migration: v2.9.0_003_creator_conversation_targets.sql
-- Source SHA-256: 2687ed9e58816a88fa9188cc90568b25be079f357eaaac8ee1d3b84eb5af3277
-- Execute after Workbench consolidation and public creator identity initialization.
-- History payloads remain in place; only the executor and operation target change.
DO $migration$
DECLARE
    marker_id CONSTANT text := '__once_creator_conversation_targets_v1';
    owner_id CONSTANT text := 'asset_owner_tenant_id';
    kind text;
    executor_id integer;
    trigger_row record;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('system-agent-release:nl2agent_main'));
    PERFORM pg_advisory_xact_lock(hashtext('system-agent-release:nl2skill_main'));
    IF EXISTS (SELECT 1 FROM nexent.schema_migrations WHERE migration_id = marker_id) THEN
        RETURN;
    END IF;
    ALTER TABLE nexent.conversation_record_t ADD COLUMN IF NOT EXISTS target jsonb;
    COMMENT ON COLUMN nexent.conversation_record_t.target IS
        'Creator operation target: {type: agent|skill, id: positive resource ID}; NULL before creation';
    ALTER TABLE nexent.conversation_record_t ADD CONSTRAINT conversation_target_shape CHECK (
        target IS NULL OR COALESCE(
            jsonb_typeof(target) = 'object'
            AND target - 'type' - 'id' = '{}'::jsonb
            AND target->>'type' IN ('agent', 'skill')
            AND jsonb_typeof(target->'id') = 'number'
            AND target->>'id' ~ '^[1-9][0-9]*$', false)
    );
    CREATE TEMP TABLE _creator_triggers ON COMMIT DROP AS
    SELECT t.tgname, t.tgenabled FROM pg_trigger t
    WHERE t.tgrelid = 'nexent.conversation_record_t'::regclass
        AND NOT t.tgisinternal AND t.tgenabled <> 'D';
    FOR trigger_row IN SELECT * FROM _creator_triggers LOOP
        EXECUTE format('ALTER TABLE nexent.conversation_record_t DISABLE TRIGGER %I', trigger_row.tgname);
    END LOOP;
    FOREACH kind IN ARRAY ARRAY['agent', 'skill'] LOOP
        SELECT agent_id INTO executor_id FROM nexent.ag_tenant_agent_t
        WHERE tenant_id = owner_id AND agent_origin = 'SYSTEM'
            AND system_key = 'nl2' || kind || '_main' AND version_no = 0 AND delete_flag = 'N';
        IF executor_id IS NULL THEN
            RAISE EXCEPTION 'Missing public nl2%_main identity; apply v2.9.0_002_shared_creator_identities.sql first', kind;
        END IF;
        UPDATE nexent.conversation_record_t SET
            target = CASE WHEN target IS NOT NULL THEN target
                WHEN kind = 'agent' AND agent_id IS NOT NULL AND agent_id > 0 AND agent_id <> executor_id
                THEN jsonb_build_object('type', kind, 'id', agent_id)
                ELSE NULL END,
            agent_id = executor_id
        WHERE workbench_config->>'mode' = kind || '_create';
        -- Legacy Skill streams contain generated files, not a reliable saved Skill ID.
    END LOOP;
    FOR trigger_row IN SELECT * FROM _creator_triggers LOOP
        EXECUTE format('ALTER TABLE nexent.conversation_record_t ENABLE %s TRIGGER %I',
            CASE trigger_row.tgenabled WHEN 'A' THEN 'ALWAYS' WHEN 'R' THEN 'REPLICA' ELSE '' END,
            trigger_row.tgname);
    END LOOP;
    INSERT INTO nexent.schema_migrations (migration_id, checksum, status, source_file)
    VALUES (marker_id, 'one-shot-v1', 'applied', 'v2.9.0_003_creator_conversation_targets.sql');
END;
$migration$;

-- Source migration: v2.9.0_004_agent_execution.sql
-- Source SHA-256: b5ac710d71dfa30f0d10ea8bf7ca98e8b09d2110699c33ede39027b5313048f2

CREATE TABLE IF NOT EXISTS nexent.agent_execution_t (
    run_id VARCHAR(32) PRIMARY KEY,
    conversation_id INTEGER NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    owner_id VARCHAR(32),
    lease_until TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL CHECK (status IN ('starting', 'running', 'completed', 'failed', 'stopped')),
    cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE,
    resource_versions JSONB NOT NULL DEFAULT '{}',
    assistant_message_id INTEGER,
    journal_repair_pending BOOLEAN NOT NULL DEFAULT FALSE,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N',
    CHECK (jsonb_typeof(resource_versions) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_agent_execution_active_conversation
    ON nexent.agent_execution_t (conversation_id)
    WHERE delete_flag = 'N' AND status IN ('starting', 'running');
CREATE INDEX IF NOT EXISTS idx_agent_execution_lease
    ON nexent.agent_execution_t (lease_until)
    WHERE delete_flag = 'N' AND status IN ('starting', 'running');
CREATE INDEX IF NOT EXISTS idx_agent_execution_repair
    ON nexent.agent_execution_t (update_time)
    WHERE delete_flag = 'N' AND journal_repair_pending;

CREATE INDEX IF NOT EXISTS idx_agent_execution_message
    ON nexent.agent_execution_t (assistant_message_id)
    WHERE delete_flag = 'N' AND assistant_message_id IS NOT NULL;

COMMENT ON TABLE nexent.agent_execution_t IS 'Runtime-owned AgentOS execution lifecycle independent of the output retention window.';
COMMENT ON COLUMN nexent.agent_execution_t.run_id IS 'Stable AgentOS execution identifier.';
COMMENT ON COLUMN nexent.agent_execution_t.conversation_id IS 'Logical reference to the owned conversation.';
COMMENT ON COLUMN nexent.agent_execution_t.tenant_id IS 'Signed tenant scope at admission.';
COMMENT ON COLUMN nexent.agent_execution_t.owner_id IS 'Runtime process identifier that renews the lease.';
COMMENT ON COLUMN nexent.agent_execution_t.status IS 'Durable execution phase or terminal result.';
COMMENT ON COLUMN nexent.agent_execution_t.cancellation_requested IS 'Durable stop request for this execution only.';
COMMENT ON COLUMN nexent.agent_execution_t.journal_repair_pending IS 'Whether reconciliation must attempt to append the retained SSE terminal event.';
COMMENT ON COLUMN nexent.agent_execution_t.resource_versions IS 'Resolved agent, model and conversation configuration versions, without execution payloads or credentials.';
COMMENT ON COLUMN nexent.agent_execution_t.lease_until IS 'Database-clock deadline after which another Runtime can recover this execution.';
COMMENT ON COLUMN nexent.agent_execution_t.assistant_message_id IS 'Logical reference to the exact assistant projection committed by this run.';

ALTER TABLE nexent.agent_automation_run_t ADD COLUMN IF NOT EXISTS runtime_run_id VARCHAR(32);
COMMENT ON COLUMN nexent.agent_automation_run_t.runtime_run_id IS 'AgentOS execution identifier assigned before dispatch; null for legacy runs.';

-- Source migration: v2.9.0_004_model_outlet_profile_columns.sql
-- Source SHA-256: 23307278b4c585ce59a1114d088d753ace256be33db88560417d605ae8fb9415

-- Add resolved outlet storage without inferring legacy model capabilities.
-- Existing configuration values remain in their original columns.
ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS reasoning_supported BOOLEAN,
    ADD COLUMN IF NOT EXISTS reasoning_controls JSONB,
    ADD COLUMN IF NOT EXISTS native_tool_call_supported BOOLEAN,
    ADD COLUMN IF NOT EXISTS structured_output_supported BOOLEAN,
    ADD COLUMN IF NOT EXISTS temperature_supported BOOLEAN,
    ADD COLUMN IF NOT EXISTS top_p_supported BOOLEAN,
    ADD COLUMN IF NOT EXISTS input_modalities JSONB,
    ADD COLUMN IF NOT EXISTS output_modalities JSONB,
    ADD COLUMN IF NOT EXISTS enable_thinking BOOLEAN,
    ADD COLUMN IF NOT EXISTS reasoning_effort VARCHAR(30),
    ADD COLUMN IF NOT EXISTS reasoning_budget_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS protocol_id VARCHAR(30),
    ADD COLUMN IF NOT EXISTS resolved_profile JSONB,
    ADD COLUMN IF NOT EXISTS profile_schema_version INTEGER,
    ADD COLUMN IF NOT EXISTS config_revision INTEGER NOT NULL DEFAULT 1;

COMMENT ON COLUMN nexent.model_record_t.reasoning_supported IS 'Reasoning support: true supported, false unsupported, NULL unknown.';
COMMENT ON COLUMN nexent.model_record_t.reasoning_controls IS 'Declared reasoning control domains; NULL unknown, empty array no controls.';
COMMENT ON COLUMN nexent.model_record_t.native_tool_call_supported IS 'Native tool call support; NULL unknown, not an execution guarantee.';
COMMENT ON COLUMN nexent.model_record_t.structured_output_supported IS 'Structured output support; NULL unknown, formats require binding.';
COMMENT ON COLUMN nexent.model_record_t.temperature_supported IS 'Temperature control support; NULL unknown, separate from parameter value.';
COMMENT ON COLUMN nexent.model_record_t.top_p_supported IS 'Top-p control support; NULL unknown, separate from parameter value.';
COMMENT ON COLUMN nexent.model_record_t.input_modalities IS 'Unique supported input modality names; NULL unknown, empty array no modalities.';
COMMENT ON COLUMN nexent.model_record_t.output_modalities IS 'Unique supported output modality names; NULL unknown, empty array no modalities.';
COMMENT ON COLUMN nexent.model_record_t.enable_thinking IS 'Saved thinking switch; NULL omitted unless marked as explicit JSON null.';
COMMENT ON COLUMN nexent.model_record_t.reasoning_effort IS 'Saved reasoning effort; NULL omitted unless marked as explicit JSON null.';
COMMENT ON COLUMN nexent.model_record_t.reasoning_budget_tokens IS 'Saved reasoning token budget; sentinel values require explicit declaration.';
COMMENT ON COLUMN nexent.model_record_t.protocol_id IS 'Registered model protocol; NULL only before resolved outlet migration completes.';
COMMENT ON COLUMN nexent.model_record_t.resolved_profile IS 'Remaining resolved rules, bindings and provenance; no copies of dedicated column values.';
COMMENT ON COLUMN nexent.model_record_t.profile_schema_version IS 'Persisted resolved profile schema version; NULL for pre-migration rows.';
COMMENT ON COLUMN nexent.model_record_t.config_revision IS 'Outlet configuration revision for optimistic updates; initial value 1.';

-- Source migration: v2.9.0_005_automation_run_projection.sql
-- Source SHA-256: 1c4d5d6329eb66d8f5f53460d2a3b6a376a5a81aa8a8f4f458046c9ca1b7fe59

ALTER TABLE nexent.agent_automation_run_t
    ADD COLUMN IF NOT EXISTS projection_message_index INTEGER;

COMMENT ON COLUMN nexent.agent_automation_run_t.projection_message_index IS
    'Assistant message index while Management is reconciling an AgentOS execution.';

CREATE INDEX IF NOT EXISTS idx_agent_automation_pending_projection
    ON nexent.agent_automation_run_t (run_id)
    WHERE delete_flag = 'N' AND projection_message_index IS NOT NULL;

-- Source migration: v2.9.0_005_model_output_default.sql
-- Source SHA-256: b8975c18ee70c62577518e33d1c44f36d21a394e6a3edad3a74749c4c18966e8

-- Preserve the existing hard output cap; store the LLM request default once.
ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS default_max_output_tokens INTEGER;
COMMENT ON COLUMN nexent.model_record_t.default_max_output_tokens IS
    'Saved LLM request output default; separate from the hard output cap. NULL omitted unless explicitly marked null.';

-- Source migration: v2.9.0_006_conversation_model_preferences.sql
-- Source SHA-256: af15cb284cc0c207bed2ab14096825c3c166b3bc0dc8241d9ab920150a201d96

ALTER TABLE nexent.conversation_record_t ADD COLUMN IF NOT EXISTS selected_model_id INTEGER;
COMMENT ON COLUMN nexent.conversation_record_t.selected_model_id IS
    'Root model selected for this Agent conversation; NULL inherits the Agent default.';

-- Extend existing conversation configuration; preferences never enter model-visible metadata.
ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS model_parameter_preferences JSONB NOT NULL DEFAULT '{}'::jsonb;
-- Remove the retired revision from earlier deployments of this PR.
ALTER TABLE nexent.conversation_record_t
    DROP COLUMN IF EXISTS model_parameter_preferences_version;
COMMENT ON COLUMN nexent.conversation_record_t.model_parameter_preferences IS
    'Explicit parameter preferences keyed by outlet ID for this conversation; no credentials or default-value copies.';

-- Source migration: v2.9.0_006_prepared_conversation_turn.sql
-- Source SHA-256: c004a30272b012732e985a9ef38d49fc0ca5aa3dbfad47112c576615a5a17654

ALTER TABLE nexent.conversation_run_admission_t
    ADD COLUMN IF NOT EXISTS prepared_user_turn JSONB,
    ADD COLUMN IF NOT EXISTS prepared_message_index INTEGER,
    ADD COLUMN IF NOT EXISTS prepared_assistant_id INTEGER;

COMMENT ON COLUMN nexent.conversation_run_admission_t.prepared_user_turn IS
    'Uncommitted user message and conversation settings retained until Runtime admission is resolved.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.prepared_message_index IS
    'Assistant message index while Management must reconcile this prepared run.';
COMMENT ON COLUMN nexent.conversation_run_admission_t.prepared_assistant_id IS
    'Assistant message reserved by Management for this admitted run.';

CREATE INDEX IF NOT EXISTS idx_conversation_admission_pending_projection
    ON nexent.conversation_run_admission_t (conversation_id, run_id)
    WHERE delete_flag = 'N' AND prepared_message_index IS NOT NULL;

ALTER TABLE nexent.conversation_message_t ADD COLUMN IF NOT EXISTS streaming_owner VARCHAR(16);
COMMENT ON COLUMN nexent.conversation_message_t.streaming_owner IS
    'Service that owns terminal repair for this streaming assistant message. NULL means legacy Runtime ownership.';

-- Source migration: v2.9.0_007_agentos_automation_callback.sql
-- Source SHA-256: 887af63ac1f16c2efcbbe9424729aec801b9fb7005b4aaf17bca9f0251c77c8a

ALTER TABLE nexent.conversation_run_admission_t
    ADD COLUMN IF NOT EXISTS prepared_automation_context JSONB;

COMMENT ON COLUMN nexent.conversation_run_admission_t.prepared_automation_context IS
    'Authorized scheduled-task proposal settings and persisted source message for the pending prepared run.';

-- Source migration: v2.9.0_007_model_http_headers.sql
-- Source SHA-256: b34b649ca88dfb585c274aacb0dc36d825263963372411c5ebad81ce9a582497

ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS http_headers JSONB NOT NULL DEFAULT '{}'::jsonb;
COMMENT ON COLUMN nexent.model_record_t.http_headers IS
    'Credential-bearing custom HTTP headers; never included in outlet snapshots or public API values.';

-- Source migration: v2.9.0_008_prepared_memory_completion.sql
-- Source SHA-256: 9080aac89efa4003744bc9c926969684e2faae83cc13f6878d42732256c8eba8

CREATE TABLE IF NOT EXISTS nexent.conversation_memory_completion_t (
    job_id VARCHAR(48) PRIMARY KEY,
    run_id VARCHAR(32) NOT NULL,
    job_type VARCHAR(20) NOT NULL CHECK (job_type IN ('turn_completed', 'final_answer')),
    agent_id INTEGER NOT NULL CHECK (agent_id > 0),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_token VARCHAR(32),
    finished_at TIMESTAMPTZ,
    selected_items JSONB CHECK (selected_items IS NULL OR jsonb_typeof(selected_items) = 'array'),
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS idx_conversation_memory_completion_ready
    ON nexent.conversation_memory_completion_t (next_attempt_at, job_id)
    WHERE finished_at IS NULL AND delete_flag = 'N';

COMMENT ON TABLE nexent.conversation_memory_completion_t IS
    'Recoverable Memory jobs committed with prepared conversation projection receipts.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.job_id IS 'Deterministic identifier derived from the run ID and Memory job type.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.run_id IS 'AgentOS run of the committed assistant projection.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.job_type IS 'Completed-turn external ingestion or final-answer extraction.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.agent_id IS 'Authorized root Agent pinned during conversation admission.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.attempts IS 'Number of worker lease claims for this job.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.next_attempt_at IS 'Next eligible claim time, or expiration time of the current lease.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.lease_token IS 'Worker token required to checkpoint or settle this claim.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.finished_at IS 'Time the job finished or stopped after its retry limit.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.selected_items IS 'Temporary array of selected Memory strings, cleared on settlement.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.created_by IS 'User who owns the assistant projection.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.updated_by IS 'Owning user on whose behalf the queue state is updated.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.create_time IS 'Time the projection committed the job.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.update_time IS 'Time the queue state was last updated.';
COMMENT ON COLUMN nexent.conversation_memory_completion_t.delete_flag IS 'Soft-deletion marker used when claiming pending work.';

-- Source migration: v2.9.0_008_unify_conversation_model_parameters.sql
-- Source SHA-256: 17caf199bd8713186f461923ba08f2155259131da1990468b4e54a9bf4fca4aa

-- Upgrade only historical Workbench declarations. New preferences win per field.
-- Discard unassigned historical preferences rather than blocking the upgrade.
WITH historical AS (
    SELECT conversation_id, workbench_config AS config,
           workbench_config->'generation_config' AS generation,
           COALESCE(workbench_config->>'model_id', selected_model_id::text) AS model_key
    FROM nexent.conversation_record_t
    WHERE jsonb_typeof(workbench_config) = 'object'
      AND (workbench_config ? 'generation_config' OR workbench_config ? 'model_parameters_source'
           OR workbench_config->>'schema_version' = '3')
), converted AS (
    SELECT *, CASE
        WHEN model_key IS NOT NULL
         AND COALESCE(config->>'model_parameters_source', 'legacy_generation') = 'legacy_generation'
        THEN jsonb_strip_nulls(jsonb_build_object(
            'temperature', generation->'temperature',
            'top_p', generation->'top_p',
            'enable_thinking', generation->'deep_thinking',
            'reasoning_budget_tokens', CASE WHEN generation->>'deep_thinking' = 'true'
                AND COALESCE((generation->>'reasoning_budget_tokens')::bigint, 0) > 0
                THEN generation->'reasoning_budget_tokens' END,
            'reasoning_effort', CASE WHEN generation->>'deep_thinking' = 'true'
                AND COALESCE((generation->>'reasoning_budget_tokens')::bigint, 0) = 0
                AND generation->>'thinking_effort' <> 'auto'
                THEN generation->'thinking_effort' END
        )) ELSE '{}'::jsonb END AS preferences
    FROM historical
)
UPDATE nexent.conversation_record_t AS target
SET selected_model_id = COALESCE(target.selected_model_id, converted.model_key::integer),
    model_parameter_preferences = CASE WHEN converted.model_key IS NULL THEN '{}'::jsonb
        WHEN converted.preferences <> '{}'::jsonb
        THEN target.model_parameter_preferences || jsonb_build_object(converted.model_key,
            (CASE WHEN target.model_parameter_preferences->converted.model_key ?| ARRAY['reasoning_effort', 'reasoning_budget_tokens']
                    OR target.model_parameter_preferences->converted.model_key->>'enable_thinking' = 'false'
                THEN converted.preferences - 'reasoning_effort' - 'reasoning_budget_tokens'
                ELSE converted.preferences END)
            || COALESCE(target.model_parameter_preferences->converted.model_key, '{}'::jsonb))
        ELSE target.model_parameter_preferences END,
    workbench_config = (converted.config - 'generation_config' - 'model_parameters_source' - 'model_id')
        || jsonb_build_object('schema_version', 4)
        || CASE WHEN converted.generation->>'requested_output_tokens' IS NOT NULL
            THEN jsonb_build_object('requested_output_tokens', converted.generation->'requested_output_tokens')
            ELSE '{}'::jsonb END,
    workbench_config_version = target.workbench_config_version + 1,
    updated_by = 'migration:session-model-parameters',
    update_time = CURRENT_TIMESTAMP
FROM converted
WHERE target.conversation_id = converted.conversation_id;

-- Source migration: v2.9.0_009_allow_mcp_header_passthrough.sql
-- Source SHA-256: 57de6188a0bf9506e6ed1b8e91cdb2ecfe6c883dcc38b00152df67d1bb92e894

-- Phase 1 of northbound MCP header passthrough feature: per-agent opt-in switch.
-- Default is FALSE so existing agents are not affected.

ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS allow_mcp_header_passthrough BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.allow_mcp_header_passthrough IS
    'Whether this agent allows northbound callers to inject per-request HTTP headers into the MCP session via metadata._mcp_headers*; disabled by default to prevent silent cross-tenant header leakage';

-- Source migration: v2.9.0_009_automation_memory_scope.sql
-- Source SHA-256: 2fc662f24e0de45d460c2af90624cc578e80a54d7070b2e4dd209bd4365da2d9

ALTER TABLE nexent.agent_automation_run_t
    ADD COLUMN IF NOT EXISTS projection_memory_agent_id INTEGER CHECK (projection_memory_agent_id > 0);

COMMENT ON COLUMN nexent.agent_automation_run_t.projection_memory_agent_id IS
    'Authorized Agent used for Memory completion by the pending AgentOS projection.';

ALTER TABLE nexent.conversation_memory_completion_t
    ADD COLUMN IF NOT EXISTS source_message_id INTEGER CHECK (source_message_id > 0);

COMMENT ON COLUMN nexent.conversation_memory_completion_t.source_message_id IS
    'Original automation prompt message ID, required for automation jobs. Chat jobs locate their paired prompt by index.';

-- Source migration: v2.9.0_009_retire_legacy_volcano_voice_models.sql
-- Source SHA-256: 425f3531fd797c6b8981305ef8ac27ed2ccb6e0c76f4be54ce9579e6ec7d5a70

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

-- Source migration: v2.9.0_009_system_configuration.sql
-- Source SHA-256: ae653dc514fecde6e655d552926c06fe6768f16c84c09995c12cc650e1356338
-- Create the single system configuration table and seed built-in values once.

SELECT pg_advisory_xact_lock(hashtext('nexent_system_configuration'));

CREATE TABLE IF NOT EXISTS nexent.sys_configuration_t (
    configuration_id SERIAL PRIMARY KEY,
    configuration_key VARCHAR(100) NOT NULL,
    configuration_value JSONB NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100) NOT NULL,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N',
    CONSTRAINT ck_sys_configuration_scalar
        CHECK (jsonb_typeof(configuration_value) IN ('number', 'boolean')),
    CONSTRAINT ck_sys_configuration_delete_flag
        CHECK (delete_flag IN ('N', 'Y'))
);

COMMENT ON TABLE nexent.sys_configuration_t IS 'System-level hot-update configuration values';
COMMENT ON COLUMN nexent.sys_configuration_t.configuration_id IS 'System configuration record identifier';
COMMENT ON COLUMN nexent.sys_configuration_t.configuration_key IS 'Stable managed configuration key with one active row enforced by locked writers';
COMMENT ON COLUMN nexent.sys_configuration_t.configuration_value IS 'Validated numeric or boolean configuration scalar';
COMMENT ON COLUMN nexent.sys_configuration_t.created_by IS 'Creating user or system actor';
COMMENT ON COLUMN nexent.sys_configuration_t.create_time IS 'Creation timestamp';
COMMENT ON COLUMN nexent.sys_configuration_t.updated_by IS 'Last updating user or system actor';
COMMENT ON COLUMN nexent.sys_configuration_t.update_time IS 'Last update timestamp';
COMMENT ON COLUMN nexent.sys_configuration_t.delete_flag IS 'Soft-delete marker with values N or Y';

CREATE INDEX IF NOT EXISTS ix_sys_configuration_active_key
    ON nexent.sys_configuration_t (configuration_key)
    WHERE delete_flag = 'N';

INSERT INTO nexent.sys_configuration_t (
    configuration_key,
    configuration_value,
    created_by,
    updated_by,
    delete_flag
)
SELECT seed.configuration_key, seed.configuration_value, 'system', 'system', 'N'
FROM (
    VALUES
    ('MAX_TENANT_COUNT', '100'::jsonb),
    ('MAX_USERS_PER_TENANT', '10000'::jsonb),
    ('MAX_GROUPS_PER_TENANT', '1000'::jsonb),
    ('MAX_SUPER_ADMIN_COUNT', '1'::jsonb),
    ('MAX_ADMINS_PER_TENANT', '1000'::jsonb),
    ('MAX_KNOWLEDGE_BASES_PER_TENANT', '10000'::jsonb),
    ('MAX_KNOWLEDGE_BASES_PER_USER', '10'::jsonb),
    ('MAX_PRIVILEGED_KNOWLEDGE_BASES_PER_USER', '1000'::jsonb),
    ('MAX_KNOWLEDGE_FILE_SIZE_MB', '100'::jsonb),
    ('MAX_CONVERSATION_TURNS', '100'::jsonb),
    ('MAX_CONVERSATIONS_PER_USER', '1000'::jsonb),
    ('MAX_MCP_SERVICES_PER_TENANT', '1000'::jsonb),
    ('MCP_REQUEST_TIMEOUT_SECONDS', '10'::jsonb),
    ('MAX_EVALUATION_SET_FILE_SIZE_MB', '20'::jsonb),
    ('RUNTIME_MCP_TOOL_TIMEOUT_SECONDS', '60'::jsonb),
    ('RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS', '120'::jsonb),
    ('LLM_INCLUDE_LOGPROBS', 'false'::jsonb),
    ('MAX_SKILLS_PER_TENANT', '1000'::jsonb),
    ('MAX_SKILL_UPLOAD_SIZE_MB', '10'::jsonb)
) AS seed(configuration_key, configuration_value)
WHERE NOT EXISTS (
    SELECT 1
    FROM nexent.sys_configuration_t AS existing
    WHERE existing.configuration_key = seed.configuration_key
      AND existing.delete_flag = 'N'
);

DO $system_configuration_role$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'nexent_configuration_reader'
    ) THEN
        CREATE ROLE nexent_configuration_reader NOLOGIN;
    END IF;
END
$system_configuration_role$;

GRANT USAGE ON SCHEMA nexent TO nexent_configuration_reader;
GRANT SELECT ON nexent.sys_configuration_t TO nexent_configuration_reader;

DO $system_configuration_role_grant$
BEGIN
    EXECUTE format('GRANT nexent_configuration_reader TO %I', current_user);
END
$system_configuration_role_grant$;

-- Source migration: v2.9.0_010_account_and_ops_roles.sql
-- Source SHA-256: 5cac58f687c5a9d4d17bf500fc862bbdb03e105c1dd3d3e5aaa01eea55590704
-- Finalize account roles, invitation grants and operations permissions.
DO $account_and_ops_roles$
DECLARE
    invalid_ids text;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('account-writers'));
    LOCK TABLE nexent.user_account_t, nexent.user_tenant_t IN SHARE ROW EXCLUSIVE MODE;

    -- Preserve arrays from the unpublished multi-role schema without retaining aliases.
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='roles') THEN
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='user_roles') THEN
            RAISE EXCEPTION 'Resolve simultaneous roles and user_roles columns before upgrade';
        END IF;
        ALTER TABLE nexent.user_account_t RENAME COLUMN roles TO user_roles;
    END IF;
    ALTER TABLE nexent.user_account_t ADD COLUMN IF NOT EXISTS user_roles VARCHAR(30)[];

    -- to_jsonb allows safe replay after the old scalar column has been removed.
    UPDATE nexent.user_account_t a
    SET user_roles=CASE WHEN nullif(to_jsonb(a)->>'user_role','') IS NULL THEN ARRAY[]::VARCHAR(30)[]
        ELSE ARRAY[to_jsonb(a)->>'user_role']::VARCHAR(30)[] END,
        updated_by='account-role-migration', update_time=CURRENT_TIMESTAMP
    WHERE a.user_roles IS NULL;

    SELECT string_agg(a.user_id, ',') INTO invalid_ids FROM nexent.user_account_t a
    WHERE a.delete_flag='N'
      AND EXISTS (SELECT 1 FROM nexent.user_tenant_t u WHERE u.user_id=a.user_id AND u.delete_flag='N')
      AND 'SPEED'=ANY(a.user_roles) AND cardinality(array_remove(a.user_roles,'SPEED'))=0;
    IF invalid_ids IS NOT NULL THEN
        RAISE EXCEPTION 'Resolve active SPEED-only accounts before upgrade: %',invalid_ids;
    END IF;
    UPDATE nexent.user_account_t SET user_roles=array_remove(user_roles,'SPEED'),
        updated_by='account-role-migration', update_time=CURRENT_TIMESTAMP
    WHERE 'SPEED'=ANY(user_roles);

    IF EXISTS (SELECT 1 FROM nexent.user_account_t a
               WHERE a.delete_flag='N'
                 AND EXISTS (SELECT 1 FROM nexent.user_tenant_t u WHERE u.user_id=a.user_id AND u.delete_flag='N')
                 AND (cardinality(a.user_roles)=0 OR array_position(a.user_roles,NULL) IS NOT NULL
                   OR NOT a.user_roles <@ ARRAY['SU','ADMIN','DEV','USER','OPS','ASSET_OWNER']::VARCHAR(30)[]
                   OR (a.user_roles && ARRAY['SU','ASSET_OWNER']::VARCHAR(30)[] AND cardinality(a.user_roles)>1))) THEN
        RAISE EXCEPTION 'Resolve missing or unknown account roles before upgrade';
    END IF;
    ALTER TABLE nexent.user_account_t ALTER COLUMN user_roles SET NOT NULL;
    ALTER TABLE nexent.user_account_t ALTER COLUMN user_roles SET DEFAULT '{}'::VARCHAR(30)[];
    COMMENT ON COLUMN nexent.user_account_t.user_roles IS
        'Authoritative built-in account roles; empty until assigned within registration';
    ALTER TABLE nexent.user_account_t DROP COLUMN IF EXISTS user_role;

    -- The historical credential import prepares only the account schema.
    -- The startup SQL runner applies the remaining changes after that import commits.
    IF current_setting('nexent.account_import', true) = 'on' THEN
        RETURN;
    END IF;

    LOCK TABLE nexent.tenant_invitation_code_t, nexent.role_permission_t IN SHARE ROW EXCLUSIVE MODE;
    ALTER TABLE nexent.tenant_invitation_code_t ADD COLUMN IF NOT EXISTS roles VARCHAR(30)[];
    IF EXISTS (SELECT 1 FROM nexent.tenant_invitation_code_t
               WHERE delete_flag='N' AND roles IS NOT NULL
                 AND cardinality(array_remove(roles,'SPEED'))=0) THEN
        RAISE EXCEPTION 'Resolve SPEED-only invitations before upgrade';
    END IF;
    UPDATE nexent.tenant_invitation_code_t
    SET roles=array_remove(COALESCE(roles, CASE code_type
        WHEN 'ADMIN_INVITE' THEN ARRAY['ADMIN']::VARCHAR(30)[]
        WHEN 'DEV_INVITE' THEN ARRAY['DEV']::VARCHAR(30)[]
        WHEN 'USER_INVITE' THEN ARRAY['USER']::VARCHAR(30)[]
        WHEN 'ASSET_OWNER_INVITE' THEN ARRAY['ASSET_OWNER']::VARCHAR(30)[] END), 'SPEED'),
        updated_by='ops-role-migration', update_time=CURRENT_TIMESTAMP
    WHERE roles IS NULL OR 'SPEED'=ANY(roles);
    IF EXISTS (SELECT 1 FROM nexent.tenant_invitation_code_t
               WHERE delete_flag='N' AND (roles IS NULL OR cardinality(roles)=0
                 OR array_position(roles,NULL) IS NOT NULL
                 OR NOT roles <@ ARRAY['ADMIN','DEV','USER','OPS','ASSET_OWNER']::VARCHAR(30)[]
                 OR ('ASSET_OWNER'=ANY(roles) AND cardinality(roles)>1))) THEN
        RAISE EXCEPTION 'Resolve unknown invitation roles before upgrade';
    END IF;
    UPDATE nexent.tenant_invitation_code_t SET roles=ARRAY[]::VARCHAR(30)[] WHERE roles IS NULL;

    ALTER TABLE nexent.tenant_invitation_code_t ALTER COLUMN roles SET NOT NULL;
    COMMENT ON COLUMN nexent.tenant_invitation_code_t.roles IS 'Immutable built-in roles granted by this invitation';
    DELETE FROM nexent.role_permission_t WHERE user_role='SPEED';
    -- Historical explicit primary keys did not advance the SERIAL sequence.
    PERFORM setval('nexent.role_permission_t_role_permission_id_seq', GREATEST(
        (SELECT COALESCE(MAX(role_permission_id),1) FROM nexent.role_permission_t),
        (SELECT last_value FROM nexent.role_permission_t_role_permission_id_seq)), true);

    -- Existing role permission storage remains the only grant/menu source.
    INSERT INTO nexent.role_permission_t
        (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
    SELECT nextval('nexent.role_permission_t_role_permission_id_seq'), r.role_code,
           'RESOURCE', g.permission_type, g.permission_subtype
    FROM (VALUES ('OPS'),('SU')) AS r(role_code)
    CROSS JOIN (VALUES
        ('OPS.DASHBOARD','READ'),('OPS.DASHBOARD','CREATE'),('OPS.DASHBOARD','UPDATE'),('OPS.DASHBOARD','DELETE'),
        ('OPS.CONFIGURATION','READ'),('OPS.CONFIGURATION','CREATE'),('OPS.CONFIGURATION','UPDATE'),('OPS.CONFIGURATION','DELETE'),
        ('RESOURCE.INVENTORY','READ')) AS g(permission_type,permission_subtype)
    WHERE NOT EXISTS (SELECT 1 FROM nexent.role_permission_t p WHERE p.user_role=r.role_code
        AND p.permission_category='RESOURCE' AND p.permission_type=g.permission_type
        AND p.permission_subtype=g.permission_subtype);

    INSERT INTO nexent.role_permission_t
        (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
    SELECT nextval('nexent.role_permission_t_role_permission_id_seq'), r.role_code,
           'VISIBILITY','LEFT_NAV_MENU',m.route
    FROM (VALUES ('OPS'),('SU')) AS r(role_code)
    CROSS JOIN (VALUES ('/ops/dashboard'),('/ops/configuration'),('/resource-manage')) AS m(route)
    WHERE NOT EXISTS (SELECT 1 FROM nexent.role_permission_t p WHERE p.user_role=r.role_code
        AND p.permission_type='LEFT_NAV_MENU' AND p.permission_subtype=m.route);
END $account_and_ops_roles$;

-- Source migration: v2.9.0_011_trajectory.sql
-- Source SHA-256: dfb13f8a8199147a9728f29016e86a584c3a8c99a693c3e599d9655f866bc12d

-- Deploy with all old trajectory writers/readers/cleaners stopped before switching lock layout.

BEGIN;

CREATE TABLE IF NOT EXISTS nexent.trajectory_execution_t (
    trajectory_id UUID NOT NULL,
    conversation_id INTEGER NOT NULL,
    turn_no INTEGER NOT NULL,
    agent_id INTEGER,
    agent_version_no INTEGER,
    models VARCHAR(100)[] DEFAULT '{}' NOT NULL,
    status VARCHAR(30) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    duration_ms DOUBLE PRECISION,
    input_tokens BIGINT,
    output_tokens BIGINT,
    total_tokens BIGINT,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    PRIMARY KEY (trajectory_id)
);

COMMENT ON COLUMN nexent.trajectory_execution_t.trajectory_id IS 'Stable root execution UUID shared with OTLP';

COMMENT ON COLUMN nexent.trajectory_execution_t.conversation_id IS 'Existing conversation business identifier';

COMMENT ON COLUMN nexent.trajectory_execution_t.turn_no IS 'Serialized execution order; zero denotes a historical placeholder';

COMMENT ON COLUMN nexent.trajectory_execution_t.agent_id IS 'Actual root Agent for this execution';

COMMENT ON COLUMN nexent.trajectory_execution_t.agent_version_no IS 'Captured root Agent version; zero is a draft';

COMMENT ON COLUMN nexent.trajectory_execution_t.models IS 'Distinct physical model names, at most 1000 values';

COMMENT ON COLUMN nexent.trajectory_execution_t.status IS 'Capture availability or terminal business result';

COMMENT ON COLUMN nexent.trajectory_execution_t.started_at IS 'Observed execution start in UTC';

COMMENT ON COLUMN nexent.trajectory_execution_t.finished_at IS 'Observed execution finish in UTC';

COMMENT ON COLUMN nexent.trajectory_execution_t.duration_ms IS 'Root elapsed milliseconds, never a sum of child spans';

COMMENT ON COLUMN nexent.trajectory_execution_t.input_tokens IS 'Input tokens; NULL if any model call has unknown input usage';

COMMENT ON COLUMN nexent.trajectory_execution_t.output_tokens IS 'Output tokens; NULL if any model call has unknown output usage';

COMMENT ON COLUMN nexent.trajectory_execution_t.total_tokens IS 'Total tokens; NULL if any model call has unknown total usage';

COMMENT ON COLUMN nexent.trajectory_execution_t.create_time IS 'Creation time';

COMMENT ON COLUMN nexent.trajectory_execution_t.update_time IS 'Update time';

COMMENT ON COLUMN nexent.trajectory_execution_t.created_by IS 'Creator';

COMMENT ON COLUMN nexent.trajectory_execution_t.updated_by IS 'Updater';

COMMENT ON COLUMN nexent.trajectory_execution_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

CREATE INDEX IF NOT EXISTS idx_trajectory_agent_started ON nexent.trajectory_execution_t (agent_id, started_at DESC, trajectory_id);

CREATE INDEX IF NOT EXISTS idx_trajectory_conversation_turn ON nexent.trajectory_execution_t (conversation_id, turn_no DESC) WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_trajectory_models ON nexent.trajectory_execution_t USING gin (models);

CREATE INDEX IF NOT EXISTS idx_trajectory_started ON nexent.trajectory_execution_t (started_at DESC, trajectory_id);

CREATE TABLE IF NOT EXISTS nexent.trajectory_statistics_t (
    statistics_id UUID NOT NULL,
    scope_type VARCHAR(30) NOT NULL,
    scope_id VARCHAR(100) NOT NULL,
    conversation_count BIGINT,
    execution_count BIGINT,
    duration_sum_ms DOUBLE PRECISION,
    duration_mean_ms DOUBLE PRECISION,
    duration_sample_count BIGINT,
    duration_p50_ms DOUBLE PRECISION,
    duration_p90_ms DOUBLE PRECISION,
    duration_p99_ms DOUBLE PRECISION,
    conversation_duration_p50_ms DOUBLE PRECISION,
    conversation_duration_p90_ms DOUBLE PRECISION,
    conversation_duration_p99_ms DOUBLE PRECISION,
    conversation_duration_sample_count BIGINT,
    ttft_p50_ms DOUBLE PRECISION,
    ttft_p90_ms DOUBLE PRECISION,
    ttft_p99_ms DOUBLE PRECISION,
    ttft_sample_count BIGINT,
    computed_at TIMESTAMP WITH TIME ZONE,
    next_refresh_at TIMESTAMP WITH TIME ZONE,
    source_revision BIGINT DEFAULT 0 NOT NULL,
    computed_revision BIGINT DEFAULT 0 NOT NULL,
    complete BOOLEAN DEFAULT false NOT NULL,
    definition_version INTEGER DEFAULT 1 NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    PRIMARY KEY (statistics_id)
);

COMMENT ON COLUMN nexent.trajectory_statistics_t.statistics_id IS 'UUID deterministically derived from scope';

COMMENT ON COLUMN nexent.trajectory_statistics_t.scope_type IS 'Statistics scope: tenant or global';

COMMENT ON COLUMN nexent.trajectory_statistics_t.scope_id IS 'Tenant identifier or global scope identifier';

COMMENT ON COLUMN nexent.trajectory_statistics_t.conversation_count IS 'All active conversations including uncaptured conversations';

COMMENT ON COLUMN nexent.trajectory_statistics_t.execution_count IS 'Actual executions excluding turn-zero placeholders';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_sum_ms IS 'Sum of known persisted root execution durations, including cleaned trajectories';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_mean_ms IS 'Mean over known execution durations';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_sample_count IS 'Number of valid execution duration samples';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_p50_ms IS 'Execution duration percentile 50 with linear interpolation';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_p90_ms IS 'Execution duration percentile 90 with linear interpolation';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_p99_ms IS 'Execution duration percentile 99 with linear interpolation';

COMMENT ON COLUMN nexent.trajectory_statistics_t.conversation_duration_p50_ms IS 'Percentile 50 of complete per-conversation duration sums';

COMMENT ON COLUMN nexent.trajectory_statistics_t.conversation_duration_p90_ms IS 'Percentile 90 of complete per-conversation duration sums';

COMMENT ON COLUMN nexent.trajectory_statistics_t.conversation_duration_p99_ms IS 'Percentile 99 of complete per-conversation duration sums';

COMMENT ON COLUMN nexent.trajectory_statistics_t.conversation_duration_sample_count IS 'Number of valid conversation duration sums';

COMMENT ON COLUMN nexent.trajectory_statistics_t.ttft_p50_ms IS 'Model first-token percentile 50 from verified OTLP files';

COMMENT ON COLUMN nexent.trajectory_statistics_t.ttft_p90_ms IS 'Model first-token percentile 90 from verified OTLP files';

COMMENT ON COLUMN nexent.trajectory_statistics_t.ttft_p99_ms IS 'Model first-token percentile 99 from verified OTLP files';

COMMENT ON COLUMN nexent.trajectory_statistics_t.ttft_sample_count IS 'Number of valid model TTFT samples including zero';

COMMENT ON COLUMN nexent.trajectory_statistics_t.computed_at IS 'Publication time of the last complete snapshot';

COMMENT ON COLUMN nexent.trajectory_statistics_t.next_refresh_at IS 'Next background refresh deadline';

COMMENT ON COLUMN nexent.trajectory_statistics_t.source_revision IS 'Monotonic source change counter';

COMMENT ON COLUMN nexent.trajectory_statistics_t.computed_revision IS 'Source counter used by the published result';

COMMENT ON COLUMN nexent.trajectory_statistics_t.complete IS 'A complete snapshot has been published';

COMMENT ON COLUMN nexent.trajectory_statistics_t.definition_version IS 'Metric definition revision';

COMMENT ON COLUMN nexent.trajectory_statistics_t.create_time IS 'Creation time';

COMMENT ON COLUMN nexent.trajectory_statistics_t.update_time IS 'Update time';

COMMENT ON COLUMN nexent.trajectory_statistics_t.created_by IS 'Creator';

COMMENT ON COLUMN nexent.trajectory_statistics_t.updated_by IS 'Updater';

COMMENT ON COLUMN nexent.trajectory_statistics_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

INSERT INTO nexent.trajectory_execution_t (trajectory_id,conversation_id,turn_no,agent_id,models,status,created_by,updated_by,delete_flag)

SELECT md5('trajectory:placeholder:' || c.conversation_id)::uuid,c.conversation_id,0,c.agent_id,'{}','not_captured',c.created_by,c.created_by,'N'

FROM nexent.conversation_record_t c WHERE c.delete_flag='N'

AND NOT EXISTS (SELECT 1 FROM nexent.trajectory_execution_t e WHERE e.conversation_id=c.conversation_id)

ON CONFLICT (trajectory_id) DO NOTHING;

-- Grant trajectory navigation to operations and super administrators.
SELECT pg_advisory_xact_lock(hashtext('nexent.observability.menu'));

DELETE FROM nexent.role_permission_t
WHERE permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype = '/observability'
  AND user_role NOT IN ('OPS', 'SU');

INSERT INTO nexent.role_permission_t (
    role_permission_id, user_role, permission_category, permission_type, permission_subtype
)
SELECT nextval('nexent.role_permission_t_role_permission_id_seq'),
       requested.user_role, 'VISIBILITY', 'LEFT_NAV_MENU', '/observability'
FROM (VALUES ('OPS'), ('SU')) AS requested(user_role)
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t existing
    WHERE existing.user_role = requested.user_role
      AND existing.permission_type = 'LEFT_NAV_MENU'
      AND existing.permission_subtype = '/observability'
);
COMMIT;

-- Source migration: v2.9.0_012_backfill_model_monitoring_model_id.sql
-- Source SHA-256: 202ae57b524f2645cc3c75b29e11ebe8ce32982c42d7344dd34dc9817f2db595

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

-- Source migration: v2.9.0_012_dreaming_length_tolerance.sql
-- Source SHA-256: d3a30a47b8ddf0906a87479be03fd667b48f8634a7d5460e09c9309c411cf009

ALTER TABLE nexent.memory_dreaming_schedule_t
    ADD COLUMN IF NOT EXISTS long_term_length_tolerance_percent INTEGER
        CONSTRAINT ck_memory_dreaming_length_tolerance
        CHECK (long_term_length_tolerance_percent BETWEEN 0 AND 100);

-- Source migration: v2.9.0_013_dreaming_user_config.sql
-- Source SHA-256: ca671c91f79140daabe4b0e5c25d7ef09e92a1350207782da31c6b2b1f438abb

-- Preserve user overrides while moving processing parameters out of schedules.
-- Earlier preview deployments may already have removed the legacy columns.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name = 'memory_dreaming_schedule_t'
          AND column_name = 'min_score'
    ) THEN
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
    END IF;
END
$$;

-- Source migration: v2.9.0_013_rebind_placeholder_tenant_memberships.sql
-- Source SHA-256: aa0acc409c5ae6a23a3b8c55a4f6bfecc7de2314b35cb23ac3e93378556d4fbe

-- Repair memberships that were created against the deployment placeholder tenant.
--
-- The v1 migration seeds user_tenant_t with ('user_id', 'tenant_id') and then
-- backfills tenant_config_t from it, so a fresh install only has the sentinel
-- TENANT_ID row 'tenant_id'. The super-admin bootstrap used to reuse that row
-- and bind the SU to it; OAuth provisioning stores the same sentinel. The
-- platform treats 'tenant_id' as "no tenant", so those memberships resolve to
-- an empty monitoring/model/agent scope.
--
-- This migration moves every active placeholder membership to the first real
-- tenant and provisions one when the database has none. Users that already hold
-- a membership of the real tenant keep it and their placeholder row is retired.
-- ASSET_OWNER identities and retired (system) accounts are left untouched:
-- they resolve to the virtual asset_owner_tenant_id or are not real logins.
--
-- Safe to re-run: the guard returns when no placeholder membership is left.

BEGIN;

DO $$
DECLARE
    real_tenant_id varchar(100);
    default_group_id integer;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM nexent.user_tenant_t
        WHERE delete_flag = 'N'
          AND tenant_id IN ('', 'tenant_id')
    ) THEN
        RETURN;
    END IF;

    -- 1. Reuse the first real tenant, matching the read-path ordering.
    SELECT tenant_id
    INTO real_tenant_id
    FROM nexent.tenant_config_t
    WHERE config_key = 'TENANT_ID'
      AND delete_flag = 'N'
      AND tenant_id IS NOT NULL
      AND btrim(tenant_id) <> ''
      AND tenant_id NOT IN ('tenant_id', 'asset_owner_tenant_id')
    ORDER BY create_time, tenant_config_id
    LIMIT 1;

    -- 2. Provision a real tenant when the deployment only has placeholders.
    IF real_tenant_id IS NULL THEN
        real_tenant_id := gen_random_uuid()::varchar;

        INSERT INTO nexent.tenant_config_t
            (tenant_id, value_type, config_key, config_value, created_by, updated_by, delete_flag)
        VALUES
            (real_tenant_id, 'single', 'TENANT_ID', real_tenant_id, 'system', 'system', 'N');

        INSERT INTO nexent.tenant_group_info_t
            (tenant_id, group_name, group_description, created_by, updated_by, delete_flag)
        VALUES
            (real_tenant_id, 'Default Group',
             'Default group created while repairing placeholder tenant bindings',
             'system', 'system', 'N')
        RETURNING group_id INTO default_group_id;

        INSERT INTO nexent.tenant_config_t
            (tenant_id, value_type, config_key, config_value, created_by, updated_by, delete_flag)
        VALUES
            (real_tenant_id, 'single', 'TENANT_NAME', 'Default Tenant', 'system', 'system', 'N'),
            (real_tenant_id, 'single', 'DEFAULT_GROUP_ID', default_group_id::varchar, 'system', 'system', 'N');
    END IF;

    -- 3. Give every placeholder member an active membership of the real tenant.
    --    ON CONFLICT also revives a previously retired membership row.
    INSERT INTO nexent.user_tenant_t
        (user_id, tenant_id, created_by, updated_by, delete_flag)
    SELECT DISTINCT placeholder.user_id, real_tenant_id, 'system', 'system', 'N'
    FROM nexent.user_tenant_t AS placeholder
    WHERE placeholder.delete_flag = 'N'
      AND placeholder.tenant_id IN ('', 'tenant_id')
      AND NOT EXISTS (
            SELECT 1
            FROM nexent.user_account_t AS account
            WHERE account.user_id = placeholder.user_id
              AND (account.delete_flag = 'Y'
                   OR 'ASSET_OWNER' = ANY (account.user_roles))
      )
    ON CONFLICT (user_id, tenant_id) DO UPDATE
    SET delete_flag = 'N',
        update_time = CURRENT_TIMESTAMP,
        updated_by = 'system';

    -- 4. Retire the placeholder rows now that the real membership exists.
    UPDATE nexent.user_tenant_t AS placeholder
    SET delete_flag = 'Y',
        update_time = CURRENT_TIMESTAMP,
        updated_by = 'system'
    WHERE placeholder.delete_flag = 'N'
      AND placeholder.tenant_id IN ('', 'tenant_id')
      AND EXISTS (
            SELECT 1
            FROM nexent.user_tenant_t AS moved
            WHERE moved.user_id = placeholder.user_id
              AND moved.delete_flag = 'N'
              AND moved.tenant_id = real_tenant_id
      );
END $$;

COMMIT;

-- Source migration: v2.9.0_014_drop_dreaming_schedule_parameters.sql
-- Source SHA-256: 8c0eafd28d6845a82043f420d35aa8aa1a479f941e55043a0c616ff05c847f20

-- v2.9.0_013_dreaming_user_config.sql copies the parameters before this cleanup.
ALTER TABLE nexent.memory_dreaming_schedule_t
    DROP CONSTRAINT IF EXISTS ck_memory_dreaming_length_tolerance,
    DROP COLUMN IF EXISTS min_score,
    DROP COLUMN IF EXISTS min_recall_count,
    DROP COLUMN IF EXISTS min_unique_queries,
    DROP COLUMN IF EXISTS source_limit,
    DROP COLUMN IF EXISTS long_term_max_chars,
    DROP COLUMN IF EXISTS long_term_length_tolerance_percent,
    DROP COLUMN IF EXISTS summarization_max_attempts;

-- Source migration: v2.9.0_014_su_system_configuration.sql
-- Source SHA-256: 5cfe90415f6fc02032d7d82a1711afaf593152fc4d9fe1c0bb7b71eb8c10074b
-- Restrict configuration management to SU and retire the super-administrator hot-update key.

SELECT pg_advisory_xact_lock(hashtext('nexent_system_configuration'));

UPDATE nexent.sys_configuration_t
SET delete_flag = 'Y',
    updated_by = 'system',
    update_time = CURRENT_TIMESTAMP
WHERE configuration_key = 'MAX_SUPER_ADMIN_COUNT'
  AND delete_flag = 'N';

DELETE FROM nexent.role_permission_t
WHERE user_role = 'OPS'
  AND permission_category = 'RESOURCE'
  AND permission_type = 'OPS.CONFIGURATION';

DELETE FROM nexent.role_permission_t
WHERE user_role = 'OPS'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype = '/ops/configuration';

-- Source migration: v2.9.0_015_ops_page_identifiers.sql
-- Source SHA-256: 07319ccaf495d8a9cf78e2109d1cc12b4d4660ee90d1a63c0ea2133002bbc02e

-- Preserve grant identities while separating navigation identifiers from routes.
UPDATE nexent.role_permission_t
SET permission_subtype = CASE permission_subtype
        WHEN '/ops/dashboard' THEN 'ops-dashboard'
        WHEN '/ops/configuration' THEN 'ops-configuration'
    END
WHERE permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype IN ('/ops/dashboard', '/ops/configuration');

-- Source migration: v2.9.0_016_agent_memory_switch.sql
-- Source SHA-256: 9588e579e1572849bd008adc29244d4206c73e0665ece1f7341234f210c367dc

ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS enable_memory BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.enable_memory IS
    'Whether this Agent version permits automatic memory operations';

-- Source migration: v2.9.0_017_aidp_retrieval_caps_defaults.sql
-- Source SHA-256: 374fe4e18fe69b42fc54a82a439c8615f1421d799f759509bb763840c1e40b6a
--
-- AIDP retrieval caps are positive quotas, not "0 means unlimited".
--
-- AIDP rejects hybrid_top_k=0 and treats graph_top_k=0 as its own default 5,
-- which breaks the required hybrid_top_k + graph_top_k <= top_k relation.
-- Replace the full set of AIDP-specific catalog definitions so newly
-- configured tool instances start from 5/5 with a 1-100 range. Explicit
-- values already stored on existing tool instances are intentionally
-- left untouched.
--
-- The migration is idempotent and must not be edited after release.

WITH new_defs AS (
    SELECT '[
      {"type":"integer","name":"vector_candidates","description":"Vector candidates","description_zh":"向量初步检索条数；固定整数，1–500","default":10,"optional":true,"constraints":{"ge":1,"le":500}},
      {"type":"integer","name":"full_text_candidates","description":"Full-text candidates","description_zh":"全文初步检索条数；固定整数，1–500","default":10,"optional":true,"constraints":{"ge":1,"le":500}},
      {"type":"integer","name":"hybrid_top_k","description":"Vector/full-text cap (1-100); the sum with graph_top_k must not exceed top_k","description_zh":"向量／全文返回上限；固定整数，1–100；与图谱返回上限之和不能超过返回条数上限","default":5,"optional":true,"constraints":{"ge":1,"le":100}},
      {"type":"integer","name":"graph_top_k","description":"Graph cap (1-100); the sum with hybrid_top_k must not exceed top_k","description_zh":"图谱返回上限；固定整数，1–100；与向量／全文返回上限之和不能超过返回条数上限","default":5,"optional":true,"constraints":{"ge":1,"le":100}},
      {"type":"float","name":"vector_score_threshold","description":"Vector threshold","description_zh":"向量检索分数阈值，范围 0–1","default":0.0,"optional":true,"constraints":{"ge":0.0,"le":1.0}},
      {"type":"float","name":"full_text_score_threshold","description":"Full-text threshold","description_zh":"全文检索分数阈值，范围 0–1","default":0.0,"optional":true,"constraints":{"ge":0.0,"le":1.0}},
      {"type":"float","name":"graph_score_threshold","description":"Graph threshold","description_zh":"图谱检索分数阈值，范围 0–1","default":0.0,"optional":true,"constraints":{"ge":0.0,"le":1.0}},
      {"type":"boolean","name":"graph_reranking_enable","description":"Include graph results in unified reranking","description_zh":"图谱是否参与统一重排；固定布尔值","default":true,"optional":true},
      {"type":"boolean","name":"query_expansion_enable","description":"Enable query expansion","description_zh":"是否启用查询扩展","default":false,"optional":true}
    ]'::jsonb AS defs
),
aidp_definitions AS (
    SELECT t.tool_id,
           COALESCE(
               (
                   SELECT jsonb_agg(elem ORDER BY ord)
                   FROM jsonb_array_elements(COALESCE(t.params::jsonb, '[]'::jsonb))
                        WITH ORDINALITY AS e(elem, ord)
                   WHERE elem->>'name' NOT IN (
                       SELECT value->>'name' FROM jsonb_array_elements(nd.defs)
                   )
               ),
               '[]'::jsonb
           ) || nd.defs AS new_params
    FROM nexent.ag_tool_info_t AS t
    CROSS JOIN new_defs AS nd
    WHERE t.class_name IN ('AidpSearchTool', 'IndependentAidpSearchTool')
       OR t.name IN ('aidp_search', 'ind_aidp_search')
)
UPDATE nexent.ag_tool_info_t AS t
SET params = d.new_params::json
FROM aidp_definitions AS d
WHERE t.tool_id = d.tool_id
  AND t.params::jsonb IS DISTINCT FROM d.new_params;

-- Source migration: v2.9.0_018_runtime_fixed_replicas.sql
-- Source SHA-256: e580af52c8bf4a60ac0c8ab9abf1fa3bb22657218374c05640bc1c0e603d60f8

-- Index scheduled automation occurrences that have started.
CREATE INDEX IF NOT EXISTS idx_agent_automation_run_started_occurrence
    ON nexent.agent_automation_run_t (task_id, scheduled_fire_at)
    WHERE user_message_id IS NOT NULL;

-- Index the active execution scope for admission across replicas.
ALTER TABLE nexent.agent_execution_t ADD COLUMN IF NOT EXISTS agent_scope VARCHAR(100);

COMMENT ON COLUMN nexent.agent_execution_t.agent_scope IS
    'Tenant-local Agent or Workbench identity used to enforce the admitted run limit across Runtime replicas.';

CREATE INDEX IF NOT EXISTS idx_agent_execution_active_scope
    ON nexent.agent_execution_t (tenant_id, agent_scope)
    WHERE status IN ('starting', 'running') AND delete_flag = 'N';

-- Index conversation execution history for Creator replay.
CREATE INDEX IF NOT EXISTS idx_agent_execution_conversation_history
    ON nexent.agent_execution_t (conversation_id, agent_scope, create_time DESC, run_id DESC)
    WHERE delete_flag = 'N';

-- Source migration: v2.9.0_resource_denylist.sql
-- Source SHA-256: 2a76b9f1522846cd6895fb9eb704453cc9f8a9bd1be987513e43fc447cfe75f0

ALTER TABLE nexent.sys_configuration_t
    DROP CONSTRAINT IF EXISTS ck_sys_configuration_scalar,
    DROP CONSTRAINT IF EXISTS ck_sys_configuration_value_type;

-- Preserve tool selections stored by earlier local denylist implementations.
UPDATE nexent.sys_configuration_t
SET configuration_value = jsonb_build_object('tool_names', configuration_value)
WHERE configuration_key = 'NL2AGENT_RESOURCE_DENYLIST'
    AND jsonb_typeof(configuration_value) = 'array';

ALTER TABLE nexent.sys_configuration_t ADD CONSTRAINT ck_sys_configuration_value_type CHECK (
    (configuration_key = 'NL2AGENT_RESOURCE_DENYLIST' AND jsonb_typeof(configuration_value) = 'object')
    OR (configuration_key <> 'NL2AGENT_RESOURCE_DENYLIST' AND jsonb_typeof(configuration_value) IN ('number', 'boolean'))
);

COMMENT ON COLUMN nexent.sys_configuration_t.configuration_value IS
    'Validated configuration value, including structured resource denylist settings';


-- Source migration: v2.9.0_002_mcp_ssl_verify.sql
-- Source SHA-256: 8cb8171684f8028c82ee50dbeb543bbeb81de772c772863cd022c09ec9a9f397

ALTER TABLE nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS ssl_verify BOOLEAN NOT NULL DEFAULT TRUE;
COMMENT ON COLUMN nexent.mcp_record_t.ssl_verify IS
    'Verify remote MCP server TLS certificate for discovery, health checks and agent invocation';

-- Source migration: v2.9.0_019_local_session_renewal.sql
-- Source SHA-256: 285ac4e64fac0d8e8229ef3145736c34360acac4141ef5fa8837f174e0f56a7c

CREATE TABLE IF NOT EXISTS nexent.user_local_session_t (
    session_id varchar(100) PRIMARY KEY,
    user_id varchar(100) NOT NULL,
    refresh_digest char(64) NOT NULL,
    created_at bigint NOT NULL,
    last_refreshed_at bigint NOT NULL,
    idle_expires_at bigint NOT NULL,
    absolute_expires_at bigint NOT NULL,
    revoked_at bigint,
    previous_refresh_digest char(64),
    previous_access_digest char(64),
    request_id varchar(64),
    retry_until bigint,
    rotation_nonce varchar(64),
    access_issued_at bigint,
    access_expires_at bigint
);

CREATE INDEX IF NOT EXISTS ix_user_local_session_idle_expiry
    ON nexent.user_local_session_t (idle_expires_at);

-- Source migration: v2.9.0_020_local_session_audit.sql
-- Source SHA-256: 36b51832e8e409cd3910860b22b9990462a8fdd215f33397a2798917da43e6af

ALTER TABLE nexent.user_local_session_t
    ADD COLUMN IF NOT EXISTS created_by varchar(100),
    ADD COLUMN IF NOT EXISTS create_time timestamp,
    ADD COLUMN IF NOT EXISTS updated_by varchar(100),
    ADD COLUMN IF NOT EXISTS update_time timestamp,
    ADD COLUMN IF NOT EXISTS delete_flag varchar(1) NOT NULL DEFAULT 'N';

UPDATE nexent.user_local_session_t
SET created_by = COALESCE(created_by, user_id),
    create_time = COALESCE(create_time, timezone('UTC', to_timestamp(created_at))),
    updated_by = COALESCE(updated_by, user_id),
    update_time = COALESCE(update_time, timezone('UTC', to_timestamp(COALESCE(revoked_at, last_refreshed_at))))
WHERE created_by IS NULL OR create_time IS NULL OR updated_by IS NULL OR update_time IS NULL;

ALTER TABLE nexent.user_local_session_t
    ALTER COLUMN created_by SET NOT NULL,
    ALTER COLUMN create_time SET DEFAULT timezone('UTC', CURRENT_TIMESTAMP),
    ALTER COLUMN create_time SET NOT NULL,
    ALTER COLUMN updated_by SET NOT NULL,
    ALTER COLUMN update_time SET DEFAULT timezone('UTC', CURRENT_TIMESTAMP),
    ALTER COLUMN update_time SET NOT NULL;

COMMENT ON TABLE nexent.user_local_session_t IS 'Credential state for renewable local account sessions.';
COMMENT ON COLUMN nexent.user_local_session_t.session_id IS 'Identifier signed into the session access JWT.';
COMMENT ON COLUMN nexent.user_local_session_t.user_id IS 'Account that owns this login session.';
COMMENT ON COLUMN nexent.user_local_session_t.refresh_digest IS 'SHA-256 digest of the current refresh token.';
COMMENT ON COLUMN nexent.user_local_session_t.created_at IS 'Session creation time in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.last_refreshed_at IS 'Most recent successful rotation time in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.idle_expires_at IS 'Idle expiration time in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.absolute_expires_at IS 'Latest allowed expiration time in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.revoked_at IS 'Revocation time in Unix seconds, null while unrevoked.';
COMMENT ON COLUMN nexent.user_local_session_t.previous_refresh_digest IS 'Digest of the refresh token from the preceding rotation.';
COMMENT ON COLUMN nexent.user_local_session_t.previous_access_digest IS 'Digest of the access JWT used in the preceding rotation.';
COMMENT ON COLUMN nexent.user_local_session_t.request_id IS 'Optional retry identifier for the preceding rotation.';
COMMENT ON COLUMN nexent.user_local_session_t.retry_until IS 'End of the rotation retry window in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.rotation_nonce IS 'Random value for reconstructing the last rotation result.';
COMMENT ON COLUMN nexent.user_local_session_t.access_issued_at IS 'Access JWT issue time for the last rotation in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.access_expires_at IS 'Access JWT expiration for the last rotation in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.created_by IS 'Actor that created the session.';
COMMENT ON COLUMN nexent.user_local_session_t.create_time IS 'UTC time when the session was inserted.';
COMMENT ON COLUMN nexent.user_local_session_t.updated_by IS 'Actor that most recently rotated or revoked the session.';
COMMENT ON COLUMN nexent.user_local_session_t.update_time IS 'UTC time when the session was last updated.';
COMMENT ON COLUMN nexent.user_local_session_t.delete_flag IS 'Soft-delete marker, N for current rows and Y for deleted rows.';
