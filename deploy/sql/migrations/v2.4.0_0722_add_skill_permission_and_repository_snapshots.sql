-- Migration: Add tenant-scoped skill uniqueness and group permissions; allow repository snapshots by status
-- Date: 2026-07-22
-- Description: Align skill ownership and repository status behavior with agent repository semantics.

SET search_path TO nexent;

ALTER TABLE IF EXISTS nexent.ag_skill_info_t
    DROP CONSTRAINT IF EXISTS ag_skill_info_t_skill_name_key;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM nexent.ag_skill_info_t
        WHERE tenant_id IS NOT NULL
          AND delete_flag = 'N'
        GROUP BY tenant_id, skill_name
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot enforce tenant-scoped Skill names: duplicate active (tenant_id, skill_name) rows exist';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM nexent.ag_skill_info_t
        WHERE tenant_id IS NULL
          AND delete_flag = 'N'
        GROUP BY skill_name
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot enforce global template Skill names: duplicate active skill_name rows exist';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_info_tenant_name_active
    ON nexent.ag_skill_info_t (tenant_id, skill_name)
    WHERE tenant_id IS NOT NULL AND delete_flag = 'N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_info_global_name_active
    ON nexent.ag_skill_info_t (skill_name)
    WHERE tenant_id IS NULL AND delete_flag = 'N';

COMMENT ON COLUMN nexent.ag_skill_info_t.skill_name IS
    'Skill name, unique among active skills within its tenant scope';

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
