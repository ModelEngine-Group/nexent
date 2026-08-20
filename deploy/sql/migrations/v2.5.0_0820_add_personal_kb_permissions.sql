-- ============================================================
-- v2.5.0_0820: Personal knowledge base permissions
--  1. Restore USER KB access:
--       LEFT_NAV_MENU /agent-dev (1307), /knowledges (1308)
--       KB:CREATE/READ/UPDATE/DELETE (1309-1312)
--  2. Add ADMIN/SU capacity permissions:
--       ADMIN KB.CAPACITY:READ/MANAGE (1117-1118)
--       SU KB.CAPACITY:READ/MANAGE (1004-1005)
-- No DDL changes. deploy/sql/init.sql keeps the table-structure baseline;
-- role_permission_t seeds are applied as incremental migrations.
-- ============================================================

SET search_path TO nexent;

BEGIN;

WITH permission_constants AS (
    SELECT
        'USER'::VARCHAR AS user_role,
        'ADMIN'::VARCHAR AS admin_role,
        'SU'::VARCHAR AS su_role,
        'VISIBILITY'::VARCHAR AS visibility_category,
        'RESOURCE'::VARCHAR AS resource_category,
        'LEFT_NAV_MENU'::VARCHAR AS menu_type,
        'KB'::VARCHAR AS kb_type,
        'KB.CAPACITY'::VARCHAR AS capacity_type,
        'CREATE'::VARCHAR AS create_action,
        'READ'::VARCHAR AS read_action,
        'UPDATE'::VARCHAR AS update_action,
        'DELETE'::VARCHAR AS delete_action,
        'MANAGE'::VARCHAR AS manage_action,
        '/agent-dev'::VARCHAR AS agent_dev_path
), permission_rows AS (
    SELECT menu.permission_id,
           constants.user_role,
           constants.visibility_category,
           constants.menu_type,
           menu.permission_subtype,
           menu.parent_key
    FROM permission_constants AS constants
    CROSS JOIN LATERAL (VALUES
        (1307, constants.agent_dev_path, NULL::VARCHAR),
        (1308, '/knowledges'::VARCHAR, constants.agent_dev_path)
    ) AS menu(permission_id, permission_subtype, parent_key)

    UNION ALL

    SELECT kb.permission_id,
           constants.user_role,
           constants.resource_category,
           constants.kb_type,
           kb.permission_subtype,
           NULL::VARCHAR
    FROM permission_constants AS constants
    CROSS JOIN LATERAL (VALUES
        (1309, constants.create_action),
        (1310, constants.read_action),
        (1311, constants.update_action),
        (1312, constants.delete_action)
    ) AS kb(permission_id, permission_subtype)

    UNION ALL

    SELECT capacity.permission_id,
           constants.admin_role,
           constants.resource_category,
           constants.capacity_type,
           capacity.permission_subtype,
           NULL::VARCHAR
    FROM permission_constants AS constants
    CROSS JOIN LATERAL (VALUES
        (1117, constants.read_action),
        (1118, constants.manage_action)
    ) AS capacity(permission_id, permission_subtype)

    UNION ALL

    SELECT capacity.permission_id,
           constants.su_role,
           constants.resource_category,
           constants.capacity_type,
           capacity.permission_subtype,
           NULL::VARCHAR
    FROM permission_constants AS constants
    CROSS JOIN LATERAL (VALUES
        (1004, constants.read_action),
        (1005, constants.manage_action)
    ) AS capacity(permission_id, permission_subtype)
)
INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype,
    parent_key
)
SELECT permission_id,
       user_role,
       visibility_category,
       menu_type,
       permission_subtype,
       parent_key
FROM permission_rows
ON CONFLICT (role_permission_id) DO UPDATE SET
    user_role = EXCLUDED.user_role,
    permission_category = EXCLUDED.permission_category,
    permission_type = EXCLUDED.permission_type,
    permission_subtype = EXCLUDED.permission_subtype,
    parent_key = EXCLUDED.parent_key;

COMMIT;
