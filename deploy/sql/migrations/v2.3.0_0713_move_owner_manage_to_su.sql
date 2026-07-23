-- ============================================================
-- Move /owner-manage left-nav from ASSET_OWNER to SU
-- Migration Date: 2026-07-13
-- ============================================================
-- ASSET_OWNER no longer sees the asset-admin resource management page.
-- SU gains /owner-manage (id 1003) alongside existing / and /resource-manage.
-- ============================================================

BEGIN;

-- Remove ASSET_OWNER access to /owner-manage
DELETE FROM nexent.role_permission_t
WHERE role_permission_id = 1505
   OR (
        user_role = 'ASSET_OWNER'
        AND permission_category = 'VISIBILITY'
        AND permission_type = 'LEFT_NAV_MENU'
        AND permission_subtype = '/owner-manage'
    );

-- Grant SU access to /owner-manage (idempotent)
DELETE FROM nexent.role_permission_t
WHERE role_permission_id = 1003
   OR (
        user_role = 'SU'
        AND permission_category = 'VISIBILITY'
        AND permission_type = 'LEFT_NAV_MENU'
        AND permission_subtype = '/owner-manage'
    );

INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
) VALUES (
    1003,
    'SU',
    'VISIBILITY',
    'LEFT_NAV_MENU',
    '/owner-manage'
);

COMMIT;
