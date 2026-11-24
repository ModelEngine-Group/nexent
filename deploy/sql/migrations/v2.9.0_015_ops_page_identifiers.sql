-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Preserve grant identities while separating navigation identifiers from routes.
UPDATE nexent.role_permission_t
SET permission_subtype = CASE permission_subtype
        WHEN '/ops/dashboard' THEN 'ops-dashboard'
        WHEN '/ops/configuration' THEN 'ops-configuration'
    END
WHERE permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype IN ('/ops/dashboard', '/ops/configuration');
