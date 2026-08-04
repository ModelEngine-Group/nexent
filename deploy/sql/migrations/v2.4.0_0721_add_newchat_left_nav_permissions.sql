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
    (1114, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/newchat', NULL),
    (1213, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/newchat', NULL),
    (1305, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/newchat', NULL),
    (1413, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/newchat', NULL),
    (1512, 'ASSET_OWNER', 'VISIBILITY', 'LEFT_NAV_MENU', '/newchat', NULL)
ON CONFLICT (role_permission_id) DO NOTHING;
COMMIT;
