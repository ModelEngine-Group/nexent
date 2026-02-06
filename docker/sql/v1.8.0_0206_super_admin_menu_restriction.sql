-- =============================================================================
-- File: v1.8.0_0206_super_admin_menu_restriction.sql
-- Description: Restrict Super Admin (SU) menu visibility to only 4 pages:
--   - Home page: /
--   - Tenant resources: /tenant-resources
--   - Monitoring: /monitoring
--   - User profile: /users
-- Version: 1.8.1
-- Date: 2026-02-06
-- =============================================================================

-- Step 1: Delete all LEFT_NAV_MENU permissions for SU role
-- This removes: /space, /knowledges, /mcp-tools, /models, /memory
DELETE FROM nexent.role_permission_t
WHERE user_role = 'SU'
  AND permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype IN (
    '/space',
    '/knowledges',
    '/mcp-tools',
    '/models',
    '/memory'
  );

-- Step 2: Update existing / route to use id 1 (keep original id)
UPDATE nexent.role_permission_t
SET permission_subtype = '/'
WHERE user_role = 'SU'
  AND permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND role_permission_id = 1;

-- Step 3: Ensure /tenant-resources exists with id 211
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (211, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/tenant-resources')
ON CONFLICT (role_permission_id) DO NOTHING;

-- Step 4: Ensure /monitoring exists with id 5
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (5, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring')
ON CONFLICT (role_permission_id) DO NOTHING;

-- Step 5: Ensure /users exists with id 8
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (8, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/users')
ON CONFLICT (role_permission_id) DO NOTHING;

-- Verify the changes
SELECT
    permission_subtype AS route,
    COUNT(*) AS record_count
FROM nexent.role_permission_t
WHERE user_role = 'SU'
  AND permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
GROUP BY permission_subtype
ORDER BY permission_subtype;
