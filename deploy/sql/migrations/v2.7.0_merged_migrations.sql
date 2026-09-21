-- Nexent merged SQL migrations: v2.7.0
-- Previous release tag: v2.6.0
-- Source bodies are embedded byte-for-byte in deployment order.
-- Do not reorder or rewrite sections without equivalence validation.

-- Source migration: v2.6.0_0820_add_conversation_manage_left_nav_permission.sql
-- Source SHA-256: <generated at merge time>

-- ============================================================
-- v2.6.0_0820: LEFT_NAV_MENU permission seed for /conversation-manage
-- ============================================================
-- The new "conversation management" page (/conversation-manage) is driven by
-- the backend LEFT_NAV_MENU role permission table, exactly like every other
-- sidebar route. Without these rows the menu item is invisible to every role
-- and the route guard blocks access (design RISK-3, REV-2).
--
-- Seed scope (per DECISION-2 / REV-2, converged by Leader):
--   * Granted to roles that already hold /chat (the conversation surface):
--     ADMIN, DEV, USER, SPEED, ASSET_OWNER.
--   * SU is intentionally EXCLUDED: the existing SU seed has no /chat entry,
--     so SU does not operate the conversation surface (SUG-1 wording).
--   * Idempotent: ON CONFLICT (role_permission_id) DO NOTHING.
--   * Re-runnable: SERIAL sequence is re-synchronized at the end of the
--     transaction, matching the v2.5.x bootstrap idempotency pattern.
-- No DDL changes; no index changes; no existing merged file is modified.
-- ============================================================

SET search_path TO nexent;

BEGIN;

INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype,
    parent_key
) VALUES
    (1517, 'ADMIN',        'VISIBILITY', 'LEFT_NAV_MENU', '/conversation-manage', '/chat'),
    (1518, 'DEV',          'VISIBILITY', 'LEFT_NAV_MENU', '/conversation-manage', '/chat'),
    (1519, 'USER',         'VISIBILITY', 'LEFT_NAV_MENU', '/conversation-manage', '/chat'),
    (1520, 'SPEED',        'VISIBILITY', 'LEFT_NAV_MENU', '/conversation-manage', '/chat'),
    (1521, 'ASSET_OWNER',  'VISIBILITY', 'LEFT_NAV_MENU', '/conversation-manage', '/chat')
ON CONFLICT (role_permission_id) DO NOTHING;

-- Explicit seeded IDs do not advance SERIAL sequences. Re-synchronize the
-- sequence after every currently shipped migration and keep re-runs safe.
SELECT setval(
    pg_get_serial_sequence('nexent.role_permission_t', 'role_permission_id'),
    COALESCE(MAX(role_permission_id), 1),
    MAX(role_permission_id) IS NOT NULL
)
FROM nexent.role_permission_t;

COMMIT;