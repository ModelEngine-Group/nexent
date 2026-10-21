-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

BEGIN;

-- The evaluation UI now lives at /evaluation; the orphaned /space page is retired.
-- Match semantic grants rather than historical IDs, which vary across deployments.
-- Preserve current evaluation access and non-navigation permissions.
DELETE FROM nexent.role_permission_t
WHERE permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype IN ('/space', '/space/evaluation', '/space/evaluators');

COMMIT;
