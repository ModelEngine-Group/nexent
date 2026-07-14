-- ============================================================
-- Add /aidp-knowledges route to left navigation menu
-- Migration Date: 2026-07-13
-- Description: Grant AIDP Knowledge Base configuration page
--   visibility to the same roles that have /knowledges
--   (ASSET_OWNER, ADMIN, DEV, SPEED).
--   SU and USER are intentionally excluded (same as /knowledges).
--   Idempotent: ON CONFLICT DO NOTHING allows safe re-execution.
--
-- WARNING: This script uses non-sequential IDs (222, 1114-1512)
--   to maintain compatibility with legacy deployments.
--   If migrating from v2.2.0 (max id 221), consider using
--   sequential IDs 222-225 instead for consistency.
--
-- Note: role_permission_t has 5 columns only, matching the
--   schema as defined in docker/init.sql.
-- ============================================================

BEGIN;

-- ASSET_OWNER: /aidp-knowledges (mirrors 194 for /knowledges)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (222, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/aidp-knowledges')
ON CONFLICT (role_permission_id) DO NOTHING;

-- ADMIN: /aidp-knowledges (mirrors 47 for /knowledges)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (1114, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/aidp-knowledges')
ON CONFLICT (role_permission_id) DO NOTHING;

-- DEV: /aidp-knowledges (mirrors 98 for /knowledges)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (1213, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/aidp-knowledges')
ON CONFLICT (role_permission_id) DO NOTHING;

-- SPEED: /aidp-knowledges (mirrors 149 for /knowledges)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (1413, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/aidp-knowledges')
ON CONFLICT (role_permission_id) DO NOTHING;

-- ASSET_OWNER: /aidp-knowledges (secondary entry, mirrors legacy data)
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES (1512, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/aidp-knowledges')
ON CONFLICT (role_permission_id) DO NOTHING;

COMMIT;
