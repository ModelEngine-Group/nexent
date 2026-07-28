-- Remove virtual/system tenant identity records accidentally materialized as real tenants.
-- Keep other DEFAULT_TENANT_ID configs intact because speed mode may still use them.

DELETE FROM nexent.tenant_config_t
WHERE tenant_id IN ('', 'tenant_id')
  AND config_key IN ('TENANT_ID', 'TENANT_NAME', 'DEFAULT_GROUP_ID');

DELETE FROM nexent.tenant_group_info_t
WHERE tenant_id IN ('', 'tenant_id')
  AND created_by = 'system';

UPDATE nexent.user_tenant_t
SET delete_flag = 'Y',
    updated_by = 'system_cleanup_virtual_tenant',
    update_time = NOW()
WHERE tenant_id IN ('', 'tenant_id')
  AND delete_flag = 'N';
