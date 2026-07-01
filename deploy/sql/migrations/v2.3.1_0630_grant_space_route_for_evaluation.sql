-- =============================================================================
-- Grant access to the agent evaluation page (/space/agents/{id}/evaluate)
-- Date: 2026-06-30
-- Description:
--   The agent evaluation page lives at the route prefix /space/agents/{id}/evaluate.
--   The previous menu migration (v2.2.2_0622_update_left_nav_menu.sql) removed
--   the legacy /space entry when it refactored the menu structure. As a result
--   the frontend route guard (which uses accessibleRoutes prefix matching) blocks
--   any user from entering the evaluation page with "no access permission".
--
--   This migration adds LEFT_NAV_MENU = '/space' for every role that already has
--   access to the resource-space (i.e. /agent-space). This entry is NOT rendered
--   in the side navigation (SideNavigation uses exact-match against ROUTE_CONFIG)
--   but it IS picked up by the backend as part of accessibleRoutes, so the route
--   guard will allow /space/agents/{id}/evaluate and its sub-paths.
--
--   Idempotent: uses ON CONFLICT DO NOTHING.
-- =============================================================================

SET search_path TO nexent;

BEGIN;

-- Roles that already have /resource-space (and thus /agent-space) get /space.
-- Mirrors v2.2.2_0622_update_left_nav_menu.sql IDs (16xx range) to keep the
-- scheme consistent.
INSERT INTO nexent.role_permission_t
    (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
VALUES
    (1600, 'SU',          'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
    (1601, 'ADMIN',       'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
    (1602, 'DEV',         'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
    (1603, 'SPEED',       'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
    (1604, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/space')
ON CONFLICT (role_permission_id) DO NOTHING;

COMMIT;