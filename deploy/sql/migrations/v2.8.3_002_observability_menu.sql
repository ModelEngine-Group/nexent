-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Navigation grants follow the administrator-only trajectory API policy.
-- Advisory locking serializes concurrent migration runners using this seed.
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('nexent.observability.menu'));
INSERT INTO nexent.role_permission_t (
    role_permission_id, user_role, permission_category, permission_type, permission_subtype
)
SELECT
    COALESCE((SELECT MAX(role_permission_id) FROM nexent.role_permission_t), 0)
        + ROW_NUMBER() OVER (ORDER BY requested.user_role),
    requested.user_role, 'VISIBILITY', 'LEFT_NAV_MENU', '/observability'
FROM (VALUES ('ADMIN'), ('SU')) AS requested(user_role)
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t existing
    WHERE existing.user_role = requested.user_role
      AND existing.permission_type = 'LEFT_NAV_MENU'
      AND existing.permission_subtype = '/observability'
);
COMMIT;
