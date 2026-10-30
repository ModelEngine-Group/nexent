-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- One atomic, repeat-safe upgrade for fresh, legacy and previously migrated databases.
DO $account_upgrade$
DECLARE
    old_role boolean;
    old_email boolean;
    role_expr text;
    email_expr text;
    row_data record;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('account-writers'));
CREATE TABLE IF NOT EXISTS nexent.user_account_t (
    account_id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    user_email VARCHAR(255),
    user_role VARCHAR(30),
    password_hash VARCHAR(512),
    password_hash_scheme VARCHAR(30),
    password_login_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    account_status VARCHAR(30) NOT NULL DEFAULT 'active',
    token_version INTEGER NOT NULL DEFAULT 0,
    email_confirmed_at TIMESTAMP,
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by VARCHAR(100),
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='email') THEN
        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='user_email') THEN
            IF EXISTS (SELECT 1 FROM nexent.user_account_t WHERE email IS NOT NULL AND user_email IS NOT NULL AND lower(trim(email)) <> lower(trim(user_email))) THEN
                RAISE EXCEPTION 'Account email columns conflict; resolve identities before migration';
            END IF;
            UPDATE nexent.user_account_t SET user_email=email WHERE user_email IS NULL;
            ALTER TABLE nexent.user_account_t DROP COLUMN email;
        ELSE
            ALTER TABLE nexent.user_account_t RENAME COLUMN email TO user_email;
        END IF;
    END IF;
    ALTER TABLE nexent.user_account_t ADD COLUMN IF NOT EXISTS user_email VARCHAR(255);
    ALTER TABLE nexent.user_account_t ADD COLUMN IF NOT EXISTS user_role VARCHAR(30);
    ALTER TABLE nexent.user_account_t ALTER COLUMN user_email DROP NOT NULL;
    IF EXISTS (SELECT user_id FROM nexent.user_account_t GROUP BY user_id HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'Duplicate account identities; resolve before migration';
    END IF;
    IF to_regclass('nexent.user_tenant_t') IS NOT NULL THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_tenant_t' AND column_name='user_role') INTO old_role;
        SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_tenant_t' AND column_name='user_email') INTO old_email;
        IF old_role OR old_email THEN
            role_expr := CASE WHEN old_role THEN 'nullif(upper(trim(user_role)), '''')' ELSE 'NULL::varchar' END;
            email_expr := CASE WHEN old_email THEN 'nullif(lower(trim(user_email)), '''')' ELSE 'NULL::varchar' END;
            FOR row_data IN EXECUTE format(
                'SELECT user_id, min(%1$s) AS role_value, min(%2$s) AS email_value, count(DISTINCT %1$s) AS roles, count(DISTINCT %2$s) AS emails, bool_or(delete_flag=''N'') AS is_active FROM nexent.user_tenant_t u WHERE delete_flag=''N'' OR NOT EXISTS (SELECT 1 FROM nexent.user_tenant_t live WHERE live.user_id=u.user_id AND live.delete_flag=''N'') GROUP BY user_id', role_expr, email_expr)
            LOOP
                IF row_data.roles > 1 OR row_data.emails > 1 THEN
                    RAISE EXCEPTION 'Conflicting active membership roles or emails; resolve before migration';
                END IF;
                IF EXISTS (SELECT 1 FROM nexent.user_account_t WHERE user_id=row_data.user_id) THEN
                    IF EXISTS (SELECT 1 FROM nexent.user_account_t WHERE user_id=row_data.user_id AND user_email IS NOT NULL AND row_data.email_value IS NOT NULL AND lower(trim(user_email))<>row_data.email_value) THEN
                        RAISE EXCEPTION 'Account email conflicts with membership; resolve before migration';
                    END IF;
                    UPDATE nexent.user_account_t SET
                        user_email=coalesce(user_email,row_data.email_value),
                        user_role=coalesce(user_role,row_data.role_value),
                        updated_by='account-schema-migration', update_time=CURRENT_TIMESTAMP
                    WHERE user_id=row_data.user_id
                      AND ((user_email IS NULL AND row_data.email_value IS NOT NULL) OR (user_role IS NULL AND row_data.role_value IS NOT NULL));
                ELSE
                    INSERT INTO nexent.user_account_t (user_id,user_email,user_role,account_status,password_login_enabled,source_metadata,created_by,updated_by,delete_flag)
                    VALUES (row_data.user_id,row_data.email_value,row_data.role_value,'disabled',false,
                            '{"credential_migration_pending":true}'::jsonb,'account-schema-migration','account-schema-migration',CASE WHEN row_data.is_active THEN 'N' ELSE 'Y' END);
                END IF;
            END LOOP;
        END IF;
        ALTER TABLE nexent.user_tenant_t DROP COLUMN IF EXISTS user_role;
        ALTER TABLE nexent.user_tenant_t DROP COLUMN IF EXISTS user_email;
    END IF;
    -- Historical API-only users have no auth.users row. Token evidence and an
    -- active USER/DEV membership distinguish them from incomplete login users.
    -- Only untouched migration placeholders may be activated; replay must not
    -- undo explicit account disablement, deletion or credential changes.
    IF to_regclass('nexent.user_token_info_t') IS NOT NULL AND to_regclass('nexent.user_tenant_t') IS NOT NULL THEN
        UPDATE nexent.user_account_t a SET
            account_status='active',
            user_email=NULL,
            source_metadata=(a.source_metadata - 'credential_migration_pending') || '{"api_only":true}'::jsonb,
            updated_by='account-schema-migration', update_time=CURRENT_TIMESTAMP
        WHERE a.delete_flag='N' AND a.account_status='disabled'
          AND nullif(trim(a.user_email),'') IS NULL AND upper(a.user_role) IN ('USER','DEV')
          AND a.password_hash IS NULL AND a.token_version=0 AND NOT a.password_login_enabled
          AND a.source_metadata->>'credential_migration_pending'='true'
          AND a.updated_by='account-schema-migration'
          AND EXISTS (SELECT 1 FROM nexent.user_tenant_t u WHERE u.user_id=a.user_id AND u.delete_flag='N')
          AND EXISTS (SELECT 1 FROM nexent.user_token_info_t t WHERE t.user_id=a.user_id);
    END IF;
    IF EXISTS (SELECT lower(trim(user_email)) FROM nexent.user_account_t WHERE delete_flag='N' AND user_email IS NOT NULL GROUP BY lower(trim(user_email)) HAVING count(*)>1) THEN
        RAISE EXCEPTION 'Duplicate account emails; resolve before migration';
    END IF;
CREATE INDEX IF NOT EXISTS ix_user_account_user_id ON nexent.user_account_t (user_id);
CREATE INDEX IF NOT EXISTS ix_user_account_email ON nexent.user_account_t (user_email);
COMMENT ON COLUMN nexent.user_account_t.account_id IS 'Technical account record identifier';
COMMENT ON COLUMN nexent.user_account_t.user_id IS 'Stable user UUID; account service serializes identity uniqueness';
COMMENT ON COLUMN nexent.user_account_t.user_email IS 'Normalized lowercase login email; null for API-only users or pending legacy profiles';
COMMENT ON COLUMN nexent.user_account_t.password_hash IS 'Encoded password hash; never exposed by user APIs';
COMMENT ON COLUMN nexent.user_account_t.password_hash_scheme IS 'Hash scheme: scrypt or imported bcrypt';
COMMENT ON COLUMN nexent.user_account_t.password_login_enabled IS 'Whether password authentication is permitted';
COMMENT ON COLUMN nexent.user_account_t.account_status IS 'Authentication state: active or disabled';
COMMENT ON COLUMN nexent.user_account_t.token_version IS 'Credential revision invalidating earlier JWTs';
COMMENT ON COLUMN nexent.user_account_t.email_confirmed_at IS 'UTC email confirmation time; null if unconfirmed';
COMMENT ON COLUMN nexent.user_account_t.source_metadata IS 'Migration/provider provenance and API-only identity marker; never grants permissions';
COMMENT ON COLUMN nexent.user_account_t.created_by IS 'Creating user or migration actor';
COMMENT ON COLUMN nexent.user_account_t.create_time IS 'UTC creation time';
COMMENT ON COLUMN nexent.user_account_t.updated_by IS 'Last updating user or migration actor';
COMMENT ON COLUMN nexent.user_account_t.update_time IS 'UTC last update time';
COMMENT ON COLUMN nexent.user_account_t.delete_flag IS 'Soft deletion marker: N active record, Y deleted';
COMMENT ON COLUMN nexent.user_account_t.user_role IS 'Canonical account role transferred from original membership data';
END
$account_upgrade$;
