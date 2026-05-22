-- Migration: Use asset_owner_tenant_id as the virtual tenant for ASSET_OWNER scope
-- Date: 2026-05-19

-- User tenant relationships
UPDATE nexent.user_tenant_t
SET tenant_id = 'asset_owner_tenant_id'
WHERE user_role = 'ASSET_OWNER'
  AND (tenant_id = '' OR tenant_id IS NULL);

-- Invitation codes for asset owners
UPDATE nexent.tenant_invitation_code_t
SET tenant_id = 'asset_owner_tenant_id'
WHERE code_type = 'ASSET_OWNER_INVITE'
  AND (tenant_id = '' OR tenant_id IS NULL);

-- Resource tables: migrate empty-string tenant scope only
UPDATE nexent.model_record_t
SET tenant_id = 'asset_owner_tenant_id'
WHERE tenant_id = '';

UPDATE nexent.ag_tenant_agent_t
SET tenant_id = 'asset_owner_tenant_id'
WHERE tenant_id = '';

UPDATE nexent.ag_tool_instance_t
SET tenant_id = 'asset_owner_tenant_id'
WHERE tenant_id = '';

UPDATE nexent.ag_tool_info_t
SET author = 'asset_owner_tenant_id'
WHERE author = '';

UPDATE nexent.ag_skill_info_t
SET tenant_id = 'asset_owner_tenant_id'
WHERE tenant_id = '';

UPDATE nexent.ag_skill_instance_t
SET tenant_id = 'asset_owner_tenant_id'
WHERE tenant_id = '';

UPDATE nexent.ag_agent_relation_t
SET tenant_id = 'asset_owner_tenant_id'
WHERE tenant_id = '';

UPDATE nexent.mcp_record_t
SET tenant_id = 'asset_owner_tenant_id'
WHERE tenant_id = '';

UPDATE nexent.ag_outer_api_services
SET tenant_id = 'asset_owner_tenant_id'
WHERE tenant_id = '';

ALTER TABLE nexent.ag_skill_info_t
    ALTER COLUMN tenant_id SET DEFAULT 'asset_owner_tenant_id';

COMMENT ON COLUMN nexent.ag_skill_info_t.tenant_id IS
    'Tenant ID; asset_owner_tenant_id for ASSET_OWNER-created skills, otherwise tenant-scoped';
