-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Keep trajectory navigation aligned with operations roles and multi-role sessions.
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('nexent.observability.menu'));

DELETE FROM nexent.role_permission_t
WHERE permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype = '/observability'
  AND user_role NOT IN ('OPS', 'SU');

INSERT INTO nexent.role_permission_t (
    role_permission_id, user_role, permission_category, permission_type, permission_subtype
)
SELECT nextval('nexent.role_permission_t_role_permission_id_seq'),
       requested.user_role, 'VISIBILITY', 'LEFT_NAV_MENU', '/observability'
FROM (VALUES ('OPS'), ('SU')) AS requested(user_role)
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t existing
    WHERE existing.user_role = requested.user_role
      AND existing.permission_type = 'LEFT_NAV_MENU'
      AND existing.permission_subtype = '/observability'
);
COMMIT;
