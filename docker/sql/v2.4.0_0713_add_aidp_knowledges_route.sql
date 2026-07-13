-- ============================================================
-- Add /aidp-knowledges route to left navigation menu
-- Migration Date: 2026-07-13
-- Description: Grant AIDP Knowledge Base configuration page
--   visibility under /agent-dev submenu to the same roles
--   that have /knowledges (ADMIN, DEV, SPEED, ASSET_OWNER).
--   SU and USER are intentionally excluded (same as /knowledges).
--   Idempotent: ON CONFLICT DO NOTHING allows safe re-execution.
-- ============================================================

BEGIN;

-- ADMIN: /aidp-knowledges under /agent-dev
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key)
VALUES (1114, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/aidp-knowledges', '/agent-dev')
ON CONFLICT (role_permission_id) DO NOTHING;

-- DEV: /aidp-knowledges under /agent-dev
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key)
VALUES (1213, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/aidp-knowledges', '/agent-dev')
ON CONFLICT (role_permission_id) DO NOTHING;

-- SPEED: /aidp-knowledges under /agent-dev
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key)
VALUES (1413, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/aidp-knowledges', '/agent-dev')
ON CONFLICT (role_permission_id) DO NOTHING;

-- ASSET_OWNER: /aidp-knowledges under /agent-dev (mirrors 1507 for /knowledges)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype, parent_key)
VALUES (1512, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/aidp-knowledges', '/agent-dev')
ON CONFLICT (role_permission_id) DO NOTHING;

-- ASSET_OWNER: /aidp-knowledges as top-level menu (mirrors 194 for /knowledges,
-- legacy entry with parent_key NULL, preserved for role that pre-dates the
-- nested /agent-dev submenu design).
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (222, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/aidp-knowledges')
ON CONFLICT (role_permission_id) DO NOTHING;

COMMIT;
