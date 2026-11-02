-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Consolidate authentication availability into the existing soft-delete marker.
DO $account_availability$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('account-writers'));
    IF to_regclass('nexent.user_account_t') IS NULL THEN
        RETURN;
    END IF;
    -- The SQL runner may replay immutable 001 after an earlier file changes.
    -- Restore its input column only inside that runner transaction; this file
    -- removes it again when replay reaches 002 normally.
    IF current_setting('nexent.account_schema_replay',true)='prepare' THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='account_status') THEN
            ALTER TABLE nexent.user_account_t ADD COLUMN account_status VARCHAR(30) NOT NULL DEFAULT 'active';
            UPDATE nexent.user_account_t SET account_status='disabled' WHERE delete_flag<>'N';
        END IF;
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='account_status') THEN
        UPDATE nexent.user_account_t SET delete_flag='Y',update_time=CURRENT_TIMESTAMP,
            updated_by='account-availability-migration' WHERE account_status<>'active' AND delete_flag='N';
        ALTER TABLE nexent.user_account_t DROP COLUMN account_status;
    END IF;
    UPDATE nexent.user_account_t SET source_metadata=source_metadata - 'credential_migration_pending',
        update_time=CURRENT_TIMESTAMP,updated_by='account-availability-migration'
    WHERE source_metadata ? 'credential_migration_pending';
    COMMENT ON COLUMN nexent.user_account_t.delete_flag IS 'Account availability: N enabled, Y disabled or deleted';
    COMMENT ON COLUMN nexent.user_account_t.user_email IS 'Normalized lowercase login email; null for passwordless identities';
END
$account_availability$;
