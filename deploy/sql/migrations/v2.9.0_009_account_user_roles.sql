-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Finalize account roles independently of operations permissions or invitations.
DO $account_roles$
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
END $account_roles$;
