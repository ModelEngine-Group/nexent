-- Restore ASSET_OWNER left-nav routes that are missing after earlier migrations:
--   /newchat (1512): inserted by v2.4.0_0721, then removed by v2.4.0_0722 DELETE 1512-1517
--   /agent-tasks (1513): expected from v2.4.0_0722; ensure present for inconsistent environments
--   /users (1514): omitted when v2.2.2 rewrote LEFT_NAV_MENU, but avatar menu always links here

BEGIN;

INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype,
    parent_key
)
VALUES
    (1512, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/newchat', NULL),
    (1513, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-tasks', NULL),
    (1514, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/users', NULL)
ON CONFLICT (role_permission_id) DO UPDATE SET
    user_role = EXCLUDED.user_role,
    permission_category = EXCLUDED.permission_category,
    permission_type = EXCLUDED.permission_type,
    permission_subtype = EXCLUDED.permission_subtype,
    parent_key = EXCLUDED.parent_key;

COMMIT;
