-- Allow tenant administrators to access the new Agent configuration page.
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
    (1118, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/newagents', '/agent-dev')
ON CONFLICT (role_permission_id) DO UPDATE SET
    user_role = EXCLUDED.user_role,
    permission_category = EXCLUDED.permission_category,
    permission_type = EXCLUDED.permission_type,
    permission_subtype = EXCLUDED.permission_subtype,
    parent_key = EXCLUDED.parent_key;

COMMIT;
