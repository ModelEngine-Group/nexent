-- Migration: ASSET_OWNER role permissions and invitation type comment
-- Date: 2026-05-29
-- Description: Add ASSET_OWNER role permissions, SU asset-owner invite permissions,
--              update invitation code_type comment, and ensure ag_skill_info_t.tenant_id exists
-- Source: commit 15cece97692db2372a978cbdf21b5d5316e79f30 (init.sql)

SET search_path TO nexent;

BEGIN;

COMMENT ON COLUMN nexent.tenant_invitation_code_t.code_type IS
    'Invitation code type: ADMIN_INVITE, DEV_INVITE, USER_INVITE, ASSET_OWNER_INVITE';

INSERT INTO nexent.role_permission_t
    (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES
    (188, 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'CREATE'),
    (189, 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'READ'),
    (190, 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'UPDATE'),
    (191, 'SU', 'RESOURCE', 'INVITE.ASSET_OWNER', 'DELETE'),
    (192, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
    (193, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents'),
    (194, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
    (195, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
    (196, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
    (197, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/market'),
    (198, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
    (199, 'ASSET_OWNER', 'RESOURCE', 'AGENT', 'CREATE'),
    (200, 'ASSET_OWNER', 'RESOURCE', 'AGENT', 'READ'),
    (201, 'ASSET_OWNER', 'RESOURCE', 'AGENT', 'UPDATE'),
    (202, 'ASSET_OWNER', 'RESOURCE', 'AGENT', 'DELETE'),
    (203, 'ASSET_OWNER', 'RESOURCE', 'SKILL', 'CREATE'),
    (204, 'ASSET_OWNER', 'RESOURCE', 'SKILL', 'READ'),
    (205, 'ASSET_OWNER', 'RESOURCE', 'SKILL', 'UPDATE'),
    (206, 'ASSET_OWNER', 'RESOURCE', 'SKILL', 'DELETE'),
    (207, 'ASSET_OWNER', 'RESOURCE', 'KB', 'CREATE'),
    (208, 'ASSET_OWNER', 'RESOURCE', 'KB', 'READ'),
    (209, 'ASSET_OWNER', 'RESOURCE', 'KB', 'UPDATE'),
    (210, 'ASSET_OWNER', 'RESOURCE', 'KB', 'DELETE'),
    (211, 'ASSET_OWNER', 'RESOURCE', 'MCP', 'CREATE'),
    (212, 'ASSET_OWNER', 'RESOURCE', 'MCP', 'READ'),
    (213, 'ASSET_OWNER', 'RESOURCE', 'MCP', 'UPDATE'),
    (214, 'ASSET_OWNER', 'RESOURCE', 'MCP', 'DELETE'),
    (215, 'ASSET_OWNER', 'RESOURCE', 'MODEL', 'CREATE'),
    (216, 'ASSET_OWNER', 'RESOURCE', 'MODEL', 'READ'),
    (217, 'ASSET_OWNER', 'RESOURCE', 'MODEL', 'UPDATE'),
    (218, 'ASSET_OWNER', 'RESOURCE', 'MODEL', 'DELETE'),
    (219, 'ASSET_OWNER', 'RESOURCE', 'USER.ROLE', 'READ'),
    (220, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
    (221, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/asset-owner-resources')
ON CONFLICT (role_permission_id) DO NOTHING;

COMMIT;
