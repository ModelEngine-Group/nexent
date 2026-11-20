-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Final account schema; the host importer owns the historical credential transaction.
DO $account_upgrade$
DECLARE
    old_role boolean;
    old_email boolean;
    role_expr text;
    email_expr text;
    row_data record;
    conflict_ids json;
    system_speed boolean;
    api_only boolean;
    provider_bound boolean;
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
        token_version INTEGER NOT NULL DEFAULT 0,
        email_confirmed_at TIMESTAMP,
        source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by VARCHAR(100),
        create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_by VARCHAR(100),
        update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
    );
    -- Read old availability only when present; never recreate the retired column.
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent'
               AND table_name='user_account_t' AND column_name='account_status') THEN
        UPDATE nexent.user_account_t SET delete_flag='Y',update_time=CURRENT_TIMESTAMP,
            updated_by='account-availability-migration'
        WHERE account_status<>'active' AND delete_flag='N';
        ALTER TABLE nexent.user_account_t DROP COLUMN account_status;
    END IF;
    UPDATE nexent.user_account_t SET source_metadata=source_metadata-'credential_migration_pending',
        update_time=CURRENT_TIMESTAMP,updated_by='account-availability-migration'
    WHERE source_metadata ? 'credential_migration_pending';
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='email') THEN
        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='user_email') THEN
            SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids FROM nexent.user_account_t
            WHERE email IS NOT NULL AND user_email IS NOT NULL AND lower(trim(email))<>lower(trim(user_email));
            IF conflict_ids IS NOT NULL THEN RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids; END IF;
            UPDATE nexent.user_account_t SET user_email=email WHERE user_email IS NULL;
            ALTER TABLE nexent.user_account_t DROP COLUMN email;
        ELSE
            ALTER TABLE nexent.user_account_t RENAME COLUMN email TO user_email;
        END IF;
    END IF;
    ALTER TABLE nexent.user_account_t ADD COLUMN IF NOT EXISTS user_email VARCHAR(255);
    ALTER TABLE nexent.user_account_t ADD COLUMN IF NOT EXISTS user_role VARCHAR(30);
    ALTER TABLE nexent.user_account_t ALTER COLUMN user_email DROP NOT NULL;
    SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids FROM (
        SELECT user_id FROM nexent.user_account_t GROUP BY user_id HAVING count(*)>1
    ) duplicate_ids;
    IF conflict_ids IS NOT NULL THEN RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids; END IF;

    -- Profiles survive only for this transaction, including the subsequent host import.
    CREATE TEMP TABLE IF NOT EXISTS account_migration_profiles (
        user_id VARCHAR(100), role_value VARCHAR(30), email_value VARCHAR(255),
        roles INTEGER, emails INTEGER
    ) ON COMMIT DROP;
    TRUNCATE pg_temp.account_migration_profiles;
    IF to_regclass('nexent.user_tenant_t') IS NOT NULL THEN
        SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_tenant_t' AND column_name='user_role') INTO old_role;
        SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_tenant_t' AND column_name='user_email') INTO old_email;
        IF old_role OR old_email THEN
            role_expr := CASE WHEN old_role THEN 'nullif(upper(trim(user_role)), '''')' ELSE 'NULL::varchar' END;
            email_expr := CASE WHEN old_email THEN 'nullif(lower(trim(user_email)), '''')' ELSE 'NULL::varchar' END;
            EXECUTE format('INSERT INTO pg_temp.account_migration_profiles SELECT user_id,min(%1$s),min(%2$s),count(DISTINCT %1$s),count(DISTINCT %2$s) FROM nexent.user_tenant_t WHERE delete_flag=''N'' GROUP BY user_id',role_expr,email_expr);
            SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids
            FROM pg_temp.account_migration_profiles WHERE roles>1 OR emails>1;
            IF conflict_ids IS NOT NULL THEN RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids; END IF;
            FOR row_data IN SELECT * FROM pg_temp.account_migration_profiles LOOP
                IF EXISTS (SELECT 1 FROM nexent.user_account_t WHERE user_id=row_data.user_id) THEN
                    IF EXISTS (SELECT 1 FROM nexent.user_account_t WHERE user_id=row_data.user_id
                               AND delete_flag='N' AND user_email IS NOT NULL AND row_data.email_value IS NOT NULL
                               AND lower(trim(user_email))<>row_data.email_value) THEN
                        RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',json_build_array(row_data.user_id);
                    END IF;
                    UPDATE nexent.user_account_t SET
                        user_email=coalesce(user_email,row_data.email_value),
                        user_role=coalesce(user_role,row_data.role_value),
                        updated_by='account-schema-migration',update_time=CURRENT_TIMESTAMP
                    WHERE user_id=row_data.user_id AND delete_flag='N'
                      AND ((user_email IS NULL AND row_data.email_value IS NOT NULL)
                        OR (user_role IS NULL AND row_data.role_value IS NOT NULL));
                    CONTINUE;
                END IF;
                system_speed := false;
                api_only := false;
                provider_bound := false;
                IF row_data.user_id='user_id' AND row_data.role_value='SPEED' AND row_data.email_value IS NULL THEN
                    SELECT EXISTS (SELECT 1 FROM nexent.user_tenant_t WHERE user_id=row_data.user_id AND tenant_id='tenant_id' AND delete_flag='N')
                       AND NOT EXISTS (SELECT 1 FROM nexent.user_tenant_t WHERE user_id=row_data.user_id AND delete_flag='N' AND tenant_id IS DISTINCT FROM 'tenant_id') INTO system_speed;
                END IF;
                IF row_data.email_value IS NULL AND row_data.role_value IN ('USER','DEV')
                   AND to_regclass('nexent.user_token_info_t') IS NOT NULL THEN
                    SELECT EXISTS (SELECT 1 FROM nexent.user_token_info_t WHERE user_id=row_data.user_id) INTO api_only;
                END IF;
                IF row_data.role_value IS NOT NULL AND row_data.email_value IS NOT NULL
                   AND to_regclass('nexent.user_oauth_account_t') IS NOT NULL THEN
                    SELECT EXISTS (SELECT 1 FROM nexent.user_oauth_account_t
                                   WHERE user_id=row_data.user_id AND delete_flag='N') INTO provider_bound;
                END IF;
                IF system_speed OR api_only OR provider_bound THEN
                    INSERT INTO nexent.user_account_t
                        (user_id,user_email,user_role,password_login_enabled,source_metadata,created_by,updated_by,delete_flag)
                    VALUES (row_data.user_id,row_data.email_value,row_data.role_value,false,
                        CASE WHEN system_speed THEN '{"system_identity":"speed"}'::jsonb
                             WHEN api_only THEN '{"api_only":true}'::jsonb ELSE '{}'::jsonb END,
                        'account-schema-migration','account-schema-migration',CASE WHEN system_speed THEN 'Y' ELSE 'N' END);
                END IF;
            END LOOP;
        END IF;
        ALTER TABLE nexent.user_tenant_t DROP COLUMN IF EXISTS user_role;
        ALTER TABLE nexent.user_tenant_t DROP COLUMN IF EXISTS user_email;
    END IF;
    -- Cross-user email validation belongs after final source eligibility is known.
    -- The importer defers this check until credentials have been classified.
    IF current_setting('nexent.account_import',true) IS DISTINCT FROM 'on' THEN
        SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids FROM nexent.user_account_t
        WHERE delete_flag='N' AND lower(trim(user_email)) IN (
            SELECT lower(trim(user_email)) FROM nexent.user_account_t WHERE delete_flag='N' AND user_email IS NOT NULL
            GROUP BY lower(trim(user_email)) HAVING count(*)>1);
        IF conflict_ids IS NOT NULL THEN RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids; END IF;
    END IF;
    CREATE INDEX IF NOT EXISTS ix_user_account_user_id ON nexent.user_account_t (user_id);
    CREATE INDEX IF NOT EXISTS ix_user_account_email ON nexent.user_account_t (user_email);
    COMMENT ON COLUMN nexent.user_account_t.account_id IS 'Technical account record identifier';
    COMMENT ON COLUMN nexent.user_account_t.user_id IS 'Stable user identifier, including legacy system IDs; account service serializes identity uniqueness';
    COMMENT ON COLUMN nexent.user_account_t.user_email IS 'Normalized lowercase login email; null for passwordless identities';
    COMMENT ON COLUMN nexent.user_account_t.user_role IS 'Canonical account role transferred from original membership data';
    COMMENT ON COLUMN nexent.user_account_t.password_hash IS 'Encoded password hash; never exposed by user APIs';
    COMMENT ON COLUMN nexent.user_account_t.password_hash_scheme IS 'Hash scheme: scrypt or imported bcrypt';
    COMMENT ON COLUMN nexent.user_account_t.password_login_enabled IS 'Whether password authentication is permitted';
    COMMENT ON COLUMN nexent.user_account_t.token_version IS 'Credential revision invalidating earlier JWTs';
    COMMENT ON COLUMN nexent.user_account_t.email_confirmed_at IS 'UTC email confirmation time; null if unconfirmed';
    COMMENT ON COLUMN nexent.user_account_t.source_metadata IS 'Migration/provider provenance, API-only and system identity markers; never grants permissions';
    COMMENT ON COLUMN nexent.user_account_t.created_by IS 'Creating user or migration actor';
    COMMENT ON COLUMN nexent.user_account_t.create_time IS 'UTC creation time';
    COMMENT ON COLUMN nexent.user_account_t.updated_by IS 'Last updating user or system actor';
    COMMENT ON COLUMN nexent.user_account_t.update_time IS 'UTC last update time';
    COMMENT ON COLUMN nexent.user_account_t.delete_flag IS 'Account availability: N enabled, Y disabled or deleted';
END
$account_upgrade$;
