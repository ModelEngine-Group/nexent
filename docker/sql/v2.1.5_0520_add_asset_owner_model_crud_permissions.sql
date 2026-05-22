-- Migration: Grant ASSET_OWNER full MODEL resource permissions (CREATE, UPDATE, DELETE)
-- Date: 2026-05-20
-- Existing deployments may already have MODEL:READ from v2.1.2; this adds the missing write permissions.

INSERT INTO nexent.role_permission_t (user_role, permission_category, permission_type, permission_subtype)
SELECT 'ASSET_OWNER', 'RESOURCE', 'MODEL', perm
FROM unnest(ARRAY['CREATE', 'UPDATE', 'DELETE']) AS perm
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t
    WHERE user_role = 'ASSET_OWNER'
      AND permission_category = 'RESOURCE'
      AND permission_type = 'MODEL'
      AND permission_subtype = perm
);
