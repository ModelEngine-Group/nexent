-- =============================================================================
-- File: v1.7.9.4_0202_add_tenant_resources_route_permission.sql
-- Description: Add /tenant-resources route permission for SU and ADMIN roles
-- Version: 1.7.9.4
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

