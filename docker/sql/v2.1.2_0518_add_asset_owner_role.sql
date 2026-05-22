-- Migration: Add ASSET_OWNER role permissions and SU asset-owner invitation permissions
-- Date: 2026-05-18

INSERT INTO nexent.role_permission_t (user_role, permission_category, permission_type, permission_subtype)
SELECT 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'CREATE'
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t
    WHERE user_role = 'SU' AND permission_category = 'RESOURCE'
      AND permission_type = 'INVITE.ASSET_OWNER' AND permission_subtype = 'CREATE'
);

INSERT INTO nexent.role_permission_t (user_role, permission_category, permission_type, permission_subtype)
SELECT 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'READ'
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t
    WHERE user_role = 'SU' AND permission_category = 'RESOURCE'
      AND permission_type = 'INVITE.ASSET_OWNER' AND permission_subtype = 'READ'
);

INSERT INTO nexent.role_permission_t (user_role, permission_category, permission_type, permission_subtype)
SELECT 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'UPDATE'
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t
    WHERE user_role = 'SU' AND permission_category = 'RESOURCE'
      AND permission_type = 'INVITE.ASSET_OWNER' AND permission_subtype = 'UPDATE'
);

INSERT INTO nexent.role_permission_t (user_role, permission_category, permission_type, permission_subtype)
SELECT 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'DELETE'
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t
    WHERE user_role = 'SU' AND permission_category = 'RESOURCE'
      AND permission_type = 'INVITE.ASSET_OWNER' AND permission_subtype = 'DELETE'
);

INSERT INTO nexent.role_permission_t (user_role, permission_category, permission_type, permission_subtype)
SELECT 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', route
FROM unnest(ARRAY['/', '/agents', '/knowledges', '/chat', '/space', '/market', '/models']) AS route
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t
    WHERE user_role = 'ASSET_OWNER' AND permission_type = 'LEFT_NAV_MENU' AND permission_subtype = route
);

INSERT INTO nexent.role_permission_t (user_role, permission_category, permission_type, permission_subtype)
SELECT 'ASSET_OWNER', 'RESOURCE', res_type, perm
FROM unnest(ARRAY['AGENT', 'SKILL', 'KB', 'MCP', 'MODEL']) AS res_type
CROSS JOIN unnest(ARRAY['CREATE', 'READ', 'UPDATE', 'DELETE']) AS perm
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t
    WHERE user_role = 'ASSET_OWNER' AND permission_type = res_type AND permission_subtype = perm
);

INSERT INTO nexent.role_permission_t (user_role, permission_category, permission_type, permission_subtype)
SELECT 'ASSET_OWNER', 'RESOURCE', 'USER.ROLE', 'READ'
WHERE NOT EXISTS (
    SELECT 1 FROM nexent.role_permission_t
    WHERE user_role = 'ASSET_OWNER' AND permission_type = 'USER.ROLE' AND permission_subtype = 'READ'
);

COMMENT ON COLUMN nexent.tenant_invitation_code_t.code_type IS
    'Invitation code type: ADMIN_INVITE, DEV_INVITE, USER_INVITE, ASSET_OWNER_INVITE';
