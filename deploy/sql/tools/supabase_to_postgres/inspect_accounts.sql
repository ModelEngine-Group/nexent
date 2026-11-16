-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Session-local inspection shared by host psql and the container worker.
CREATE OR REPLACE FUNCTION pg_temp.inspect_local_accounts() RETURNS json LANGUAGE plpgsql AS $$
DECLARE
    legacy boolean := to_regclass('nexent.user_tenant_t') IS NOT NULL;
    accounts boolean := to_regclass('nexent.user_account_t') IS NOT NULL;
    members bigint := 0;
    account_count bigint := 0;
    missing_ids json := '[]';
    excluded text := 'false';
    provider text := 'false';
    api_only text := 'false';
    role_values text := 'ARRAY[]::varchar[]';
    valid_roles text;
BEGIN
    IF legacy THEN
        SELECT count(DISTINCT user_id) INTO members FROM nexent.user_tenant_t WHERE delete_flag='N';
    END IF;
    IF accounts THEN
        SELECT count(*) INTO account_count FROM nexent.user_account_t;
    END IF;
    IF legacy AND accounts THEN
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='user_roles') THEN
            role_values := 'a.user_roles';
        ELSIF EXISTS (SELECT 1 FROM information_schema.columns
                      WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='roles') THEN
            role_values := 'a.roles';
        ELSIF EXISTS (SELECT 1 FROM information_schema.columns
                      WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='user_role') THEN
            role_values := 'CASE WHEN nullif(trim(a.user_role),'''') IS NULL THEN ARRAY[]::varchar[] ELSE ARRAY[a.user_role]::varchar[] END';
        END IF;
        valid_roles := format('(cardinality(%1$s)>0 AND array_position(%1$s,NULL) IS NULL AND %1$s <@ ARRAY[''SU'',''ADMIN'',''DEV'',''USER'',''OPS'',''ASSET_OWNER'',''SPEED'']::varchar[])',role_values);
        IF to_regclass('nexent.account_migration_exclusion_t') IS NOT NULL THEN
            excluded := 'EXISTS (SELECT 1 FROM nexent.account_migration_exclusion_t e WHERE e.user_id=u.user_id AND e.delete_flag=''N'')';
        END IF;
        IF to_regclass('nexent.user_oauth_account_t') IS NOT NULL THEN
            provider := 'EXISTS (SELECT 1 FROM nexent.user_oauth_account_t p WHERE p.user_id=u.user_id AND p.delete_flag=''N'')';
        END IF;
        IF to_regclass('nexent.user_token_info_t') IS NOT NULL THEN
            api_only := format('(a.user_email IS NULL AND %s <@ ARRAY[''USER'',''DEV'']::varchar[] AND EXISTS (SELECT 1 FROM nexent.user_token_info_t t WHERE t.user_id=u.user_id))',role_values);
        END IF;
        EXECUTE format($query$
            SELECT coalesce(json_agg(user_id ORDER BY user_id),'[]'::json) FROM (
                SELECT DISTINCT u.user_id FROM nexent.user_tenant_t u
                WHERE u.delete_flag='N' AND NOT (%s) AND NOT EXISTS (
                    SELECT 1 FROM nexent.user_account_t a WHERE a.user_id=u.user_id AND (
                        (a.delete_flag='Y' AND NOT (a.source_metadata ? 'credential_migration_pending'))
                        OR (a.user_id='user_id' AND a.source_metadata->>'system_identity'='speed')
                        OR (a.delete_flag='N' AND %s AND (
                            (a.token_version>0 AND NOT a.password_login_enabled)
                            OR (a.password_login_enabled AND nullif(trim(a.user_email),'') IS NOT NULL AND nullif(a.password_hash,'') IS NOT NULL
                             AND a.password_hash_scheme IN ('bcrypt','scrypt')) OR (%s AND nullif(trim(a.user_email),'') IS NOT NULL) OR %s
                        ))
                    )
                )
            ) missing
        $query$,excluded,valid_roles,provider,api_only) INTO missing_ids;
    ELSIF legacy THEN
        SELECT coalesce(json_agg(user_id ORDER BY user_id),'[]'::json) INTO missing_ids
        FROM (SELECT DISTINCT user_id FROM nexent.user_tenant_t WHERE delete_flag='N') m;
    END IF;
    RETURN json_build_object('complete',accounts AND json_array_length(missing_ids)=0,
        'legacy',legacy,'account_table',accounts,'accounts',account_count,'members',members,'unresolved_ids',missing_ids);
END
$$;
SELECT pg_temp.inspect_local_accounts();
