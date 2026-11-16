-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
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
