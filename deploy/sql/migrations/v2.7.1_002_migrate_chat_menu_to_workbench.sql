-- Preserve existing chat menu grants as independent workbench menu grants.
UPDATE nexent.role_permission_t
SET permission_subtype = '/workbench'
WHERE permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype = '/chat';
