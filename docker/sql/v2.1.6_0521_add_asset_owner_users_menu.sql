-- Migration: Grant ASSET_OWNER access to the "/users" left-nav menu (Personal Info page)
-- Date: 2026-05-21
-- Existing deployments created before this migration do not have the "/users" entry
-- in role_permission_t for ASSET_OWNER, which hides the Personal Info tab for asset
-- owners. This migration adds the missing visibility permission idempotently.

INSERT INTO nexent.role_permission_t (user_role, permission_category, permission_type, permission_subtype)
SELECT 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t
    WHERE user_role = 'ASSET_OWNER'
      AND permission_category = 'VISIBILITY'
      AND permission_type = 'LEFT_NAV_MENU'
      AND permission_subtype = '/users'
);
