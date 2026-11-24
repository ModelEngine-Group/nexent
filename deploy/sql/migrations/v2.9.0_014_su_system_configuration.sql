-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
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
