-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
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
