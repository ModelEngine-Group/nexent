-- Migration: Add skill group permissions and allow separate repository snapshots by status
-- Date: 2026-07-22
-- Description: Align skill ownership and repository status behavior with agent repository semantics.

SET search_path TO nexent;

ALTER TABLE IF EXISTS nexent.ag_skill_info_t
    ADD COLUMN IF NOT EXISTS group_ids VARCHAR,
    ADD COLUMN IF NOT EXISTS ingroup_permission VARCHAR(30);

COMMENT ON COLUMN nexent.ag_skill_info_t.group_ids IS 'Skill group IDs list';
COMMENT ON COLUMN nexent.ag_skill_info_t.ingroup_permission IS 'In-group permission: EDIT, READ_ONLY, PRIVATE';

WITH tenant_groups AS (
    SELECT
        tenant_id,
        string_agg(group_id::text, ',' ORDER BY group_id) AS group_ids
    FROM nexent.tenant_group_info_t
    WHERE delete_flag = 'N'
    GROUP BY tenant_id
)
UPDATE nexent.ag_skill_info_t skill
SET group_ids = tenant_groups.group_ids
FROM tenant_groups
WHERE skill.tenant_id = tenant_groups.tenant_id
  AND skill.delete_flag = 'N'
  AND skill.tenant_id IS NOT NULL
  AND (skill.group_ids IS NULL OR skill.group_ids = '');

UPDATE nexent.ag_skill_info_t
SET ingroup_permission = 'EDIT'
WHERE delete_flag = 'N'
  AND tenant_id IS NOT NULL
  AND (ingroup_permission IS NULL OR ingroup_permission = '');

DROP INDEX IF EXISTS nexent.uq_skill_repository_skill_active;
DROP INDEX IF EXISTS nexent.uq_skill_repository_skill_shared_active;
DROP INDEX IF EXISTS nexent.uq_skill_repository_skill_pending_active;

CREATE INDEX IF NOT EXISTS idx_skill_repository_skill_status_delete
    ON nexent.ag_skill_repository_t (publisher_tenant_id, skill_id, status, delete_flag);

COMMENT ON COLUMN nexent.ag_skill_repository_t.skill_id IS
    'Source skill ID from ag_skill_info_t; multiple active snapshots may exist across statuses';
