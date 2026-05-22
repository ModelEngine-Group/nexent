-- Migration: Add tenant_id to ag_skill_info_t for ASSET_OWNER / tenant skill isolation
-- Date: 2026-05-19
-- tenant_id asset_owner_tenant_id marks ASSET_OWNER skills; other values scope to a tenant.

ALTER TABLE nexent.ag_skill_info_t
    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);

-- Legacy rows: assign to default tenant scope before enabling empty-string ASSET_OWNER scope
UPDATE nexent.ag_skill_info_t
SET tenant_id = 'tenant_id'
WHERE tenant_id IS NULL;

ALTER TABLE nexent.ag_skill_info_t
    ALTER COLUMN tenant_id SET DEFAULT '';

COMMENT ON COLUMN nexent.ag_skill_info_t.tenant_id IS
    'Tenant ID; asset_owner_tenant_id for ASSET_OWNER-created skills, otherwise tenant-scoped';

-- Drop global unique on skill_name; scope uniqueness per tenant (including empty for ASSET_OWNER)
ALTER TABLE nexent.ag_skill_info_t
    DROP CONSTRAINT IF EXISTS ag_skill_info_t_skill_name_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ag_skill_info_t_skill_name_tenant
    ON nexent.ag_skill_info_t (skill_name, tenant_id)
    WHERE delete_flag = 'N';
