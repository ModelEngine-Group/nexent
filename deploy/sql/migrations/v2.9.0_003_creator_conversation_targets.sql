-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
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
