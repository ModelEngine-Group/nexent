-- ============================================================
-- v2.5.0_0820: Personal knowledge base permissions
--  1. Remove legacy USER KB / KB.GROUPS resource permissions.
--  2. Restore USER KB access:
--       LEFT_NAV_MENU /knowledges (1705), /agent-dev (1714)
--       KB:CREATE/READ/UPDATE/DELETE (1706-1709)
--  3. Add ADMIN/SU capacity permissions:
--       KB.CAPACITY:READ/MANAGE (1710-1713)
-- No DDL changes. deploy/sql/init.sql keeps the table-structure baseline;
-- role_permission_t seeds are applied as incremental migrations.
-- ============================================================

SET search_path TO nexent;

BEGIN;

-- Remove legacy USER KB permissions if they still exist in inconsistent
-- environments. USER access is re-seeded below with the new ID range.
DELETE FROM nexent.role_permission_t
WHERE user_role = 'USER'
  AND permission_category = 'RESOURCE'
  AND permission_type IN ('KB', 'KB.GROUPS');

-- Remove an old USER /knowledges nav entry if present, then insert 1705.
DELETE FROM nexent.role_permission_t
WHERE user_role = 'USER'
  AND permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype = '/knowledges';

-- Remove an old USER /agent-dev nav entry if present, then insert 1714.
DELETE FROM nexent.role_permission_t
WHERE user_role = 'USER'
  AND permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype = '/agent-dev';

INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype,
    parent_key
)
VALUES
    (1705, 'USER',  'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges', '/agent-dev'),
    (1706, 'USER',  'RESOURCE',   'KB',            'CREATE',      NULL),
    (1707, 'USER',  'RESOURCE',   'KB',            'READ',        NULL),
    (1708, 'USER',  'RESOURCE',   'KB',            'UPDATE',      NULL),
    (1709, 'USER',  'RESOURCE',   'KB',            'DELETE',      NULL),
    (1710, 'ADMIN', 'RESOURCE',   'KB.CAPACITY',   'READ',        NULL),
    (1711, 'ADMIN', 'RESOURCE',   'KB.CAPACITY',   'MANAGE',      NULL),
    (1712, 'SU',    'RESOURCE',   'KB.CAPACITY',   'READ',        NULL),
    (1713, 'SU',    'RESOURCE',   'KB.CAPACITY',   'MANAGE',      NULL),
    (1714, 'USER',  'VISIBILITY', 'LEFT_NAV_MENU', '/agent-dev',  NULL)
ON CONFLICT (role_permission_id) DO UPDATE SET
    user_role = EXCLUDED.user_role,
    permission_category = EXCLUDED.permission_category,
    permission_type = EXCLUDED.permission_type,
    permission_subtype = EXCLUDED.permission_subtype,
    parent_key = EXCLUDED.parent_key;

COMMIT;
