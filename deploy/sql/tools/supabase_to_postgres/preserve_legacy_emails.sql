-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Preserve conflicting email values before historical 001 removes legacy columns.
CREATE OR REPLACE FUNCTION pg_temp.prepare_legacy_account_emails() RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    account record;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('account-writers'));
    CREATE TEMP TABLE legacy_account_emails (user_id varchar(100), emails jsonb) ON COMMIT DROP;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent'
               AND table_name='user_account_t' AND column_name='email')
       AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent'
                   AND table_name='user_account_t' AND column_name='user_email') THEN
        FOR account IN SELECT user_id, user_email, email AS legacy_email FROM nexent.user_account_t
            WHERE lower(trim(email)) <> lower(trim(user_email))
        LOOP
            RAISE WARNING 'Conflicting local account emails %', row_to_json(account);
        END LOOP;
        UPDATE nexent.user_account_t
        SET source_metadata=source_metadata || jsonb_build_object('legacy_account_email',email), email=user_email
        WHERE lower(trim(email)) <> lower(trim(user_email));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='nexent'
                   AND table_name='user_tenant_t' AND column_name='user_email') THEN
        RETURN;
    END IF;
    INSERT INTO pg_temp.legacy_account_emails
    SELECT user_id,jsonb_agg(DISTINCT jsonb_build_object('tenant_id',to_jsonb(u)->>'tenant_id','user_email',user_email))
    FROM nexent.user_tenant_t u WHERE delete_flag='N' AND nullif(trim(user_email),'') IS NOT NULL
    GROUP BY user_id HAVING count(DISTINCT lower(trim(user_email)))>1;
    IF to_regclass('nexent.user_account_t') IS NOT NULL THEN
        INSERT INTO pg_temp.legacy_account_emails
        SELECT u.user_id,jsonb_agg(DISTINCT jsonb_build_object('tenant_id',to_jsonb(u)->>'tenant_id','user_email',u.user_email))
        FROM nexent.user_tenant_t u JOIN nexent.user_account_t a ON a.user_id=u.user_id
        WHERE u.delete_flag='N' AND a.delete_flag='N'
          AND nullif(trim(u.user_email),'') IS NOT NULL
          AND lower(trim(u.user_email))<>lower(trim(coalesce(to_jsonb(a)->>'user_email',to_jsonb(a)->>'email')))
          AND NOT EXISTS (SELECT 1 FROM pg_temp.legacy_account_emails e WHERE e.user_id=u.user_id)
        GROUP BY u.user_id;
    END IF;
    FOR account IN SELECT user_id, email->>'user_email' AS user_email FROM pg_temp.legacy_account_emails,
        LATERAL jsonb_array_elements(emails) AS email ORDER BY user_id,user_email
    LOOP
        RAISE WARNING 'Conflicting legacy membership email %', row_to_json(account);
    END LOOP;
    UPDATE nexent.user_tenant_t u SET user_email=NULL
    FROM pg_temp.legacy_account_emails e WHERE u.user_id=e.user_id AND u.delete_flag='N';
END
$$;

CREATE OR REPLACE FUNCTION pg_temp.restore_legacy_account_emails() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    UPDATE nexent.user_account_t a SET source_metadata=a.source_metadata ||
        jsonb_build_object('legacy_membership_emails',e.emails)
    FROM pg_temp.legacy_account_emails e WHERE a.user_id=e.user_id;
    INSERT INTO nexent.user_account_t (user_id,user_role,source_metadata,delete_flag,created_by,updated_by)
    SELECT e.user_id,p.role_value,jsonb_build_object('legacy_membership_emails',e.emails),
           'Y','auth-migration','auth-migration'
    FROM pg_temp.legacy_account_emails e LEFT JOIN pg_temp.account_migration_profiles p USING (user_id)
    WHERE NOT EXISTS (SELECT 1 FROM nexent.user_account_t a WHERE a.user_id=e.user_id);
END
$$;
