-- =============================================================================
-- File: v1.8.0_0202_role_permission_update.sql
-- Description: Add /tenant-resources route permission and tenant list visibility for SU role
-- Version: 1.8.0
-- Date: 2026-02-02
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
