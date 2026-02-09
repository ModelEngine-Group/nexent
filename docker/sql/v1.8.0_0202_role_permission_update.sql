-- =============================================================================
-- File: v1.8.0_0202_role_permission_update.sql
-- Description: Add /tenant-resources route permission and tenant list visibility for SU role
--              Restrict Super Admin (SU) menu visibility to only 4 pages:
--                - Home page: /
--                - Tenant resources: /tenant-resources
--                - Monitoring: /monitoring
--                - User profile: /users
-- Version: 1.8.0
-- Date: 2026-02-06
-- =============================================================================

-- Add /tenant-resources LEFT_NAV_MENU permission for SU (Super Admin) role
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (211, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/tenant-resources')
ON CONFLICT (role_permission_id) DO NOTHING;

-- Add /tenant-resources LEFT_NAV_MENU permission for ADMIN (Tenant Admin) role
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (212, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/tenant-resources')
ON CONFLICT (role_permission_id) DO NOTHING;

-- Add tenant list visibility permission for SU (Super Admin) role - controls tenant list display in resource page
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (213, 'SU', 'RESOURCE', 'TENANT.LIST', 'READ')
ON CONFLICT (role_permission_id) DO NOTHING;

-- =============================================================================
-- Part 4: Restrict Super Admin (SU) menu visibility to only 4 pages
--         This removes: /space, /knowledges, /mcp-tools, /models, /memory
-- =============================================================================
-- Step 4.1: Delete all LEFT_NAV_MENU permissions for SU role
DELETE FROM nexent.role_permission_t
WHERE user_role = 'SU'
  AND permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU';

-- Step 4.2: Insert the 4 allowed routes for SU role
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1,   'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(211, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/tenant-resources'),
(5,   'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(8,   'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/users')
ON CONFLICT (role_permission_id) DO NOTHING;
