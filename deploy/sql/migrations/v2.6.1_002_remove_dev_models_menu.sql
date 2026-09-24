-- Remove the model management page from the DEV role menu.
-- Developers must not see or manage models; they only consume
-- administrator-configured models. RESOURCE MODEL READ is kept so
-- model pickers in agent editing keep working.
-- Pattern follows v2.3 migration that removed ASSET_OWNER /owner-manage.
DELETE FROM nexent.role_permission_t
WHERE user_role = 'DEV'
  AND permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype = '/models';
