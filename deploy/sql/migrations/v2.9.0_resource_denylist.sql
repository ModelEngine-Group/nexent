-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
