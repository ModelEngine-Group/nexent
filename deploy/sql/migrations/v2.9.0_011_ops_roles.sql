-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Account structure is finalized by 010; this migration owns operations grants.
BEGIN;
DO $ops_roles$
BEGIN
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
END $ops_roles$;

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

COMMIT;
