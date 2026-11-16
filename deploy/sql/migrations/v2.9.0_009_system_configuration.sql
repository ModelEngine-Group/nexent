-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
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
