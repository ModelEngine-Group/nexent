-- Delete erroneous tenant with empty tenant_id and all related data
-- This script removes records where tenant_id is empty string from tenant_config_t and tenant_group_info_t

-- 1. Force delete all records in tenant_config_t where tenant_id is empty string
DELETE FROM nexent.tenant_config_t
WHERE tenant_id = '';

-- 2. Force delete all records in tenant_group_info_t where tenant_id is empty string
DELETE FROM nexent.tenant_group_info_t
WHERE tenant_id = '';
