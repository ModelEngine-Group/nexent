-- ============================================================
-- Add aidp_kb_permission_t table for AIDP knowledge base permissions
-- Migration Date: 2026-07-23
-- Description:
--   P0 data layer for the AIDP permission redesign (v7.1).
--   - Stores one record per KB that has been claimed into Nexent.
--   - UNIQUE(kb_id) WHERE delete_flag='N' prevents concurrent active duplicates.
--   - group_ids uses JSONB for type safety and indexable intersection queries.
--   - resource_status tracks lifecycle so the API can surface UNKNOWN/ORPHANED
--     KBs without silently hiding them.
-- Idempotent: every DDL uses IF NOT EXISTS so re-running this migration is safe.
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS nexent.aidp_kb_permission_t (
    id                  BIGSERIAL PRIMARY KEY,
    kb_id               VARCHAR(128) NOT NULL,
    owner_user_id       VARCHAR(100) NOT NULL,
    tenant_id           VARCHAR(100) NOT NULL,
    ingroup_permission  VARCHAR(30)  NOT NULL DEFAULT 'READ_ONLY',
    group_ids           JSONB        NOT NULL DEFAULT '[]'::jsonb,
    resource_status     VARCHAR(30)  NOT NULL DEFAULT 'ACTIVE',
    create_time         TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time         TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by          VARCHAR(100),
    updated_by          VARCHAR(100),
    delete_flag         VARCHAR(1)   NOT NULL DEFAULT 'N'
);

-- Active-record uniqueness: only one live row per kbs_id.
-- After a soft delete the constraint releases the kb_id, allowing re-creation.
CREATE UNIQUE INDEX IF NOT EXISTS uq_aidp_kb_permission_active_kb
    ON nexent.aidp_kb_permission_t (kb_id)
    WHERE delete_flag = 'N';

-- Tenant and ownership lookup indexes; partial on active rows only.
CREATE INDEX IF NOT EXISTS idx_aidp_perm_tenant
    ON nexent.aidp_kb_permission_t (tenant_id)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_aidp_perm_user
    ON nexent.aidp_kb_permission_t (owner_user_id, tenant_id)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_aidp_perm_kb
    ON nexent.aidp_kb_permission_t (kb_id)
    WHERE delete_flag = 'N';

-- JSONB GIN index supports `group_ids @> '[1,2]'::jsonb` intersection queries
-- that the permission service uses to determine KB accessibility.
CREATE INDEX IF NOT EXISTS idx_aidp_perm_group_ids_gin
    ON nexent.aidp_kb_permission_t USING GIN (group_ids)
    WHERE delete_flag = 'N';

COMMENT ON TABLE  nexent.aidp_kb_permission_t IS
    'AIDP knowledge base permission records. Each row represents a KB under Nexent management.';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.kb_id IS
    'kds_id returned by AIDP, globally unique within AIDP system (AIDP guarantees this).';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.owner_user_id IS
    'Nexent user_id of the KB creator (Nexent account that called the AIDP create API).';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.tenant_id IS
    'Nexent tenant_id; combined with delete_flag this is the only valid query key for multi-tenant isolation.';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.ingroup_permission IS
    'Permission level for authorized groups: EDIT / READ_ONLY / PRIVATE.';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.group_ids IS
    'JSON array of Nexent group IDs authorized to access this KB. Empty array means no group access.';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.resource_status IS
    'Resource lifecycle status: CREATING / ACTIVE / DELETE_PENDING / ORPHANED / UNAVAILABLE.';
COMMENT ON COLUMN nexent.aidp_kb_permission_t.delete_flag IS
    'Y / N. Active rows are N. Soft delete flips this to Y so the active uniqueness constraint releases the kb_id.';

COMMIT;
