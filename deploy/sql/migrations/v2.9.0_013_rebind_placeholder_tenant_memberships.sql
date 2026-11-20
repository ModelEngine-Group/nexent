-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Repair memberships that were created against the deployment placeholder tenant.
--
-- The v1 migration seeds user_tenant_t with ('user_id', 'tenant_id') and then
-- backfills tenant_config_t from it, so a fresh install only has the sentinel
-- TENANT_ID row 'tenant_id'. The super-admin bootstrap used to reuse that row
-- and bind the SU to it; OAuth provisioning stores the same sentinel. The
-- platform treats 'tenant_id' as "no tenant", so those memberships resolve to
-- an empty monitoring/model/agent scope.
--
-- This migration moves every active placeholder membership to the first real
-- tenant and provisions one when the database has none. Users that already hold
-- a membership of the real tenant keep it and their placeholder row is retired.
-- ASSET_OWNER identities and retired (system) accounts are left untouched:
-- they resolve to the virtual asset_owner_tenant_id or are not real logins.
--
-- Safe to re-run: the guard returns when no placeholder membership is left.

BEGIN;

DO $$
DECLARE
    real_tenant_id varchar(100);
    default_group_id integer;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM nexent.user_tenant_t
        WHERE delete_flag = 'N'
          AND tenant_id IN ('', 'tenant_id')
    ) THEN
        RETURN;
    END IF;

    -- 1. Reuse the first real tenant, matching the read-path ordering.
    SELECT tenant_id
    INTO real_tenant_id
    FROM nexent.tenant_config_t
    WHERE config_key = 'TENANT_ID'
      AND delete_flag = 'N'
      AND tenant_id IS NOT NULL
      AND btrim(tenant_id) <> ''
      AND tenant_id NOT IN ('tenant_id', 'asset_owner_tenant_id')
    ORDER BY create_time, tenant_config_id
    LIMIT 1;

    -- 2. Provision a real tenant when the deployment only has placeholders.
    IF real_tenant_id IS NULL THEN
        real_tenant_id := gen_random_uuid()::varchar;

        INSERT INTO nexent.tenant_config_t
            (tenant_id, value_type, config_key, config_value, created_by, updated_by, delete_flag)
        VALUES
            (real_tenant_id, 'single', 'TENANT_ID', real_tenant_id, 'system', 'system', 'N');

        INSERT INTO nexent.tenant_group_info_t
            (tenant_id, group_name, group_description, created_by, updated_by, delete_flag)
        VALUES
            (real_tenant_id, 'Default Group',
             'Default group created while repairing placeholder tenant bindings',
             'system', 'system', 'N')
        RETURNING group_id INTO default_group_id;

        INSERT INTO nexent.tenant_config_t
            (tenant_id, value_type, config_key, config_value, created_by, updated_by, delete_flag)
        VALUES
            (real_tenant_id, 'single', 'TENANT_NAME', 'Default Tenant', 'system', 'system', 'N'),
            (real_tenant_id, 'single', 'DEFAULT_GROUP_ID', default_group_id::varchar, 'system', 'system', 'N');
    END IF;

    -- 3. Give every placeholder member an active membership of the real tenant.
    --    ON CONFLICT also revives a previously retired membership row.
    INSERT INTO nexent.user_tenant_t
        (user_id, tenant_id, created_by, updated_by, delete_flag)
    SELECT DISTINCT placeholder.user_id, real_tenant_id, 'system', 'system', 'N'
    FROM nexent.user_tenant_t AS placeholder
    WHERE placeholder.delete_flag = 'N'
      AND placeholder.tenant_id IN ('', 'tenant_id')
      AND NOT EXISTS (
            SELECT 1
            FROM nexent.user_account_t AS account
            WHERE account.user_id = placeholder.user_id
              AND (account.delete_flag = 'Y'
                   OR 'ASSET_OWNER' = ANY (account.user_roles))
      )
    ON CONFLICT (user_id, tenant_id) DO UPDATE
    SET delete_flag = 'N',
        update_time = CURRENT_TIMESTAMP,
        updated_by = 'system';

    -- 4. Retire the placeholder rows now that the real membership exists.
    UPDATE nexent.user_tenant_t AS placeholder
    SET delete_flag = 'Y',
        update_time = CURRENT_TIMESTAMP,
        updated_by = 'system'
    WHERE placeholder.delete_flag = 'N'
      AND placeholder.tenant_id IN ('', 'tenant_id')
      AND EXISTS (
            SELECT 1
            FROM nexent.user_tenant_t AS moved
            WHERE moved.user_id = placeholder.user_id
              AND moved.delete_flag = 'N'
              AND moved.tenant_id = real_tenant_id
      );
END $$;

COMMIT;
