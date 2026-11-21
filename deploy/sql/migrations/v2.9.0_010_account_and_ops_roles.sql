-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Finalize account roles, invitation grants and operations permissions.
DO $account_and_ops_roles$
DECLARE
    invalid_ids text;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('account-writers'));
    LOCK TABLE nexent.user_account_t, nexent.user_tenant_t IN SHARE ROW EXCLUSIVE MODE;

    -- Preserve arrays from the unpublished multi-role schema without retaining aliases.
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='roles') THEN
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='user_roles') THEN
            RAISE EXCEPTION 'Resolve simultaneous roles and user_roles columns before upgrade';
        END IF;
        ALTER TABLE nexent.user_account_t RENAME COLUMN roles TO user_roles;
    END IF;
    ALTER TABLE nexent.user_account_t ADD COLUMN IF NOT EXISTS user_roles VARCHAR(30)[];

    -- to_jsonb allows safe replay after the old scalar column has been removed.
    UPDATE nexent.user_account_t a
    SET user_roles=CASE WHEN nullif(to_jsonb(a)->>'user_role','') IS NULL THEN ARRAY[]::VARCHAR(30)[]
        ELSE ARRAY[to_jsonb(a)->>'user_role']::VARCHAR(30)[] END,
        updated_by='account-role-migration', update_time=CURRENT_TIMESTAMP
    WHERE a.user_roles IS NULL;

    SELECT string_agg(a.user_id, ',') INTO invalid_ids FROM nexent.user_account_t a
    WHERE a.delete_flag='N'
      AND EXISTS (SELECT 1 FROM nexent.user_tenant_t u WHERE u.user_id=a.user_id AND u.delete_flag='N')
      AND 'SPEED'=ANY(a.user_roles) AND cardinality(array_remove(a.user_roles,'SPEED'))=0;
    IF invalid_ids IS NOT NULL THEN
        RAISE EXCEPTION 'Resolve active SPEED-only accounts before upgrade: %',invalid_ids;
    END IF;
    UPDATE nexent.user_account_t SET user_roles=array_remove(user_roles,'SPEED'),
        updated_by='account-role-migration', update_time=CURRENT_TIMESTAMP
    WHERE 'SPEED'=ANY(user_roles);

    IF EXISTS (SELECT 1 FROM nexent.user_account_t a
               WHERE a.delete_flag='N'
                 AND EXISTS (SELECT 1 FROM nexent.user_tenant_t u WHERE u.user_id=a.user_id AND u.delete_flag='N')
                 AND (cardinality(a.user_roles)=0 OR array_position(a.user_roles,NULL) IS NOT NULL
                   OR NOT a.user_roles <@ ARRAY['SU','ADMIN','DEV','USER','OPS','ASSET_OWNER']::VARCHAR(30)[]
                   OR (a.user_roles && ARRAY['SU','ASSET_OWNER']::VARCHAR(30)[] AND cardinality(a.user_roles)>1))) THEN
        RAISE EXCEPTION 'Resolve missing or unknown account roles before upgrade';
    END IF;
    ALTER TABLE nexent.user_account_t ALTER COLUMN user_roles SET NOT NULL;
    ALTER TABLE nexent.user_account_t ALTER COLUMN user_roles SET DEFAULT '{}'::VARCHAR(30)[];
    COMMENT ON COLUMN nexent.user_account_t.user_roles IS
        'Authoritative built-in account roles; empty until assigned within registration';
    ALTER TABLE nexent.user_account_t DROP COLUMN IF EXISTS user_role;

    -- The historical credential import prepares only the account schema.
    -- The startup SQL runner applies the remaining changes after that import commits.
    IF current_setting('nexent.account_import', true) = 'on' THEN
        RETURN;
    END IF;

    LOCK TABLE nexent.tenant_invitation_code_t, nexent.role_permission_t IN SHARE ROW EXCLUSIVE MODE;
    ALTER TABLE nexent.tenant_invitation_code_t ADD COLUMN IF NOT EXISTS roles VARCHAR(30)[];
    IF EXISTS (SELECT 1 FROM nexent.tenant_invitation_code_t
               WHERE delete_flag='N' AND roles IS NOT NULL
                 AND cardinality(array_remove(roles,'SPEED'))=0) THEN
        RAISE EXCEPTION 'Resolve SPEED-only invitations before upgrade';
    END IF;
    UPDATE nexent.tenant_invitation_code_t
    SET roles=array_remove(COALESCE(roles, CASE code_type
        WHEN 'ADMIN_INVITE' THEN ARRAY['ADMIN']::VARCHAR(30)[]
        WHEN 'DEV_INVITE' THEN ARRAY['DEV']::VARCHAR(30)[]
        WHEN 'USER_INVITE' THEN ARRAY['USER']::VARCHAR(30)[]
        WHEN 'ASSET_OWNER_INVITE' THEN ARRAY['ASSET_OWNER']::VARCHAR(30)[] END), 'SPEED'),
        updated_by='ops-role-migration', update_time=CURRENT_TIMESTAMP
    WHERE roles IS NULL OR 'SPEED'=ANY(roles);
    IF EXISTS (SELECT 1 FROM nexent.tenant_invitation_code_t
               WHERE delete_flag='N' AND (roles IS NULL OR cardinality(roles)=0
                 OR array_position(roles,NULL) IS NOT NULL
                 OR NOT roles <@ ARRAY['ADMIN','DEV','USER','OPS','ASSET_OWNER']::VARCHAR(30)[]
                 OR ('ASSET_OWNER'=ANY(roles) AND cardinality(roles)>1))) THEN
        RAISE EXCEPTION 'Resolve unknown invitation roles before upgrade';
    END IF;
    UPDATE nexent.tenant_invitation_code_t SET roles=ARRAY[]::VARCHAR(30)[] WHERE roles IS NULL;

    ALTER TABLE nexent.tenant_invitation_code_t ALTER COLUMN roles SET NOT NULL;
    COMMENT ON COLUMN nexent.tenant_invitation_code_t.roles IS 'Immutable built-in roles granted by this invitation';
    DELETE FROM nexent.role_permission_t WHERE user_role='SPEED';
    -- Historical explicit primary keys did not advance the SERIAL sequence.
    PERFORM setval('nexent.role_permission_t_role_permission_id_seq', GREATEST(
        (SELECT COALESCE(MAX(role_permission_id),1) FROM nexent.role_permission_t),
        (SELECT last_value FROM nexent.role_permission_t_role_permission_id_seq)), true);

    -- Existing role permission storage remains the only grant/menu source.
    INSERT INTO nexent.role_permission_t
        (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
    SELECT nextval('nexent.role_permission_t_role_permission_id_seq'), r.role_code,
           'RESOURCE', g.permission_type, g.permission_subtype
    FROM (VALUES ('OPS'),('SU')) AS r(role_code)
    CROSS JOIN (VALUES
        ('OPS.DASHBOARD','READ'),('OPS.DASHBOARD','CREATE'),('OPS.DASHBOARD','UPDATE'),('OPS.DASHBOARD','DELETE'),
        ('OPS.CONFIGURATION','READ'),('OPS.CONFIGURATION','CREATE'),('OPS.CONFIGURATION','UPDATE'),('OPS.CONFIGURATION','DELETE'),
        ('RESOURCE.INVENTORY','READ')) AS g(permission_type,permission_subtype)
    WHERE NOT EXISTS (SELECT 1 FROM nexent.role_permission_t p WHERE p.user_role=r.role_code
        AND p.permission_category='RESOURCE' AND p.permission_type=g.permission_type
        AND p.permission_subtype=g.permission_subtype);

    INSERT INTO nexent.role_permission_t
        (role_permission_id, user_role, permission_category, permission_type, permission_subtype)
    SELECT nextval('nexent.role_permission_t_role_permission_id_seq'), r.role_code,
           'VISIBILITY','LEFT_NAV_MENU',m.route
    FROM (VALUES ('OPS'),('SU')) AS r(role_code)
    CROSS JOIN (VALUES ('/ops/dashboard'),('/ops/configuration'),('/resource-manage')) AS m(route)
    WHERE NOT EXISTS (SELECT 1 FROM nexent.role_permission_t p WHERE p.user_role=r.role_code
        AND p.permission_type='LEFT_NAV_MENU' AND p.permission_subtype=m.route);
END $account_and_ops_roles$;
