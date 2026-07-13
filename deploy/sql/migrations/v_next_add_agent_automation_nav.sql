-- Add Agent Automation task page to role-based left navigation.

ALTER TABLE nexent.role_permission_t
ADD COLUMN IF NOT EXISTS parent_key VARCHAR(50);

-- Keep the serial sequence ahead of rows inserted with explicit IDs by older migrations.
SELECT setval(
    pg_get_serial_sequence('nexent.role_permission_t', 'role_permission_id'),
    COALESCE((SELECT MAX(role_permission_id) FROM nexent.role_permission_t), 0) + 1,
    false
);

INSERT INTO nexent.role_permission_t (
    user_role,
    permission_category,
    permission_type,
    permission_subtype,
    parent_key
)
SELECT role_name, 'VISIBILITY', 'LEFT_NAV_MENU', '/agent-tasks', NULL
FROM (
    VALUES
        ('SU'),
        ('ADMIN'),
        ('DEV'),
        ('USER'),
        ('SPEED'),
        ('ASSET_OWNER')
) AS roles(role_name)
WHERE NOT EXISTS (
    SELECT 1
    FROM nexent.role_permission_t existing
    WHERE existing.user_role = roles.role_name
      AND existing.permission_category = 'VISIBILITY'
      AND existing.permission_type = 'LEFT_NAV_MENU'
      AND existing.permission_subtype = '/agent-tasks'
);
