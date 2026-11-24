-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

SELECT pg_advisory_xact_lock(hashtext('nexent_system_configuration'));

ALTER TABLE nexent.sys_configuration_t
    DROP CONSTRAINT IF EXISTS ck_sys_configuration_scalar;
ALTER TABLE nexent.sys_configuration_t
    ADD CONSTRAINT ck_sys_configuration_scalar CHECK (
        CASE WHEN configuration_key = 'NL2AGENT_RESOURCE_DENYLIST'
             THEN jsonb_typeof(configuration_value) = 'array'
             ELSE jsonb_typeof(configuration_value) IN ('number', 'boolean')
        END
    );

COMMENT ON COLUMN nexent.sys_configuration_t.configuration_value IS 'Validated system configuration value';

INSERT INTO nexent.sys_configuration_t (
    configuration_key, configuration_value, created_by, updated_by, delete_flag
)
SELECT 'NL2AGENT_RESOURCE_DENYLIST', '[]'::jsonb, 'system', 'system', 'N'
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.sys_configuration_t
    WHERE configuration_key = 'NL2AGENT_RESOURCE_DENYLIST' AND delete_flag = 'N'
);
