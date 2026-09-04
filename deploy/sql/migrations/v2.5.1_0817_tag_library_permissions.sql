BEGIN;

SET LOCAL search_path TO nexent, public;

-- tag-library-permission-seed:start
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM nexent.role_permission_t
        WHERE permission_category = 'RESOURCE'
          AND permission_type = 'TAG_LIBRARY'
          AND permission_subtype = 'MANAGE'
          AND user_role NOT IN ('SU', 'ADMIN', 'SPEED', 'ASSET_OWNER')
    ) THEN
        RAISE EXCEPTION 'TAG_LIBRARY/MANAGE is assigned to a role outside the approved set';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM nexent.role_permission_t
        WHERE permission_category = 'RESOURCE'
          AND permission_type = 'TAG_LIBRARY'
          AND permission_subtype = 'MANAGE'
        GROUP BY user_role
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'TAG_LIBRARY/MANAGE contains duplicate role grants';
    END IF;
END;
$$;

WITH required_grants (user_role, permission_category, permission_type, permission_subtype) AS (
    VALUES
        ('SU', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
        ('ADMIN', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
        ('SPEED', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
        ('ASSET_OWNER', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE')
)
INSERT INTO nexent.role_permission_t (
    user_role,
    permission_category,
    permission_type,
    permission_subtype
)
SELECT
    required_grants.user_role,
    required_grants.permission_category,
    required_grants.permission_type,
    required_grants.permission_subtype
FROM required_grants
WHERE NOT EXISTS (
    SELECT 1
    FROM nexent.role_permission_t AS existing
    WHERE existing.user_role = required_grants.user_role
      AND existing.permission_category = required_grants.permission_category
      AND existing.permission_type = required_grants.permission_type
      AND existing.permission_subtype = required_grants.permission_subtype
);
-- tag-library-permission-seed:end

COMMIT;
