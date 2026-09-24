-- Grant the resource-space navigation group to the SU role.
-- v2.2.2 rebuilt the navigation permissions but omitted these entries for SU,
-- so a super administrator who follows a publish link to /agent-space is
-- blocked by the frontend route guard even though the page itself works.
-- Keep this file idempotent: the migration runner may execute it again after
-- a checksum change in an earlier migration.

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
    (1605, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/resource-space', NULL),
    (1606, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-space', '/resource-space'),
    (1607, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-space', '/resource-space'),
    (1608, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/skill-space', '/resource-space')
ON CONFLICT (role_permission_id) DO UPDATE SET
    user_role = EXCLUDED.user_role,
    permission_category = EXCLUDED.permission_category,
    permission_type = EXCLUDED.permission_type,
    permission_subtype = EXCLUDED.permission_subtype,
    parent_key = EXCLUDED.parent_key;

-- Explicit primary keys do not advance a SERIAL sequence. Keep the sequence
-- beyond the seeded IDs so future permission inserts cannot collide.
SELECT setval(
    pg_get_serial_sequence('nexent.role_permission_t', 'role_permission_id'),
    COALESCE(MAX(role_permission_id), 1),
    MAX(role_permission_id) IS NOT NULL
)
FROM nexent.role_permission_t;

COMMIT;
