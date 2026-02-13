-- Initialize tenant group and default configuration for existing tenants
-- This migration adds default group and basic config for tenants that lack them
-- Trigger condition: tenant has no TENANT_ID config_key in tenant_config_t

DO $$
DECLARE
    target_tenant_id VARCHAR(100);
    new_group_id INTEGER;
BEGIN
    -- Loop through each distinct tenant_id from user_tenant_t
    FOR target_tenant_id IN
        SELECT DISTINCT tenant_id
        FROM nexent.user_tenant_t
        WHERE tenant_id IS NOT NULL
    LOOP
        -- Check if tenant already has TENANT_ID config_key
        IF NOT EXISTS (
            SELECT 1 FROM nexent.tenant_config_t
            WHERE tenant_id = target_tenant_id
              AND config_key = 'TENANT_ID'
              AND delete_flag = 'N'
        ) THEN
            -- Insert TENANT_ID config
            INSERT INTO nexent.tenant_config_t (
                tenant_id, user_id, value_type, config_key, config_value,
                create_time, update_time, created_by, updated_by, delete_flag
            ) VALUES (
                target_tenant_id, NULL, 'single', 'TENANT_ID', target_tenant_id,
                NOW(), NOW(), 'system', 'system', 'N'
            );

            -- Insert TENANT_NAME config if not exists
            IF NOT EXISTS (
                SELECT 1 FROM nexent.tenant_config_t
                WHERE tenant_id = target_tenant_id
                  AND config_key = 'TENANT_NAME'
                  AND delete_flag = 'N'
            ) THEN
                INSERT INTO nexent.tenant_config_t (
                    tenant_id, user_id, value_type, config_key, config_value,
                    create_time, update_time, created_by, updated_by, delete_flag
                ) VALUES (
                    target_tenant_id, NULL, 'single', 'TENANT_NAME', 'Unnamed Tenant',
                    NOW(), NOW(), 'system', 'system', 'N'
                );
            END IF;

            -- Check if tenant already has a group
            IF NOT EXISTS (
                SELECT 1 FROM nexent.tenant_group_info_t
                WHERE tenant_id = target_tenant_id
                  AND delete_flag = 'N'
            ) THEN
                -- Insert default group
                INSERT INTO nexent.tenant_group_info_t (
                    tenant_id, group_name, group_description,
                    create_time, update_time, created_by, updated_by, delete_flag
                ) VALUES (
                    target_tenant_id, 'Default Group', 'Default group for tenant',
                    NOW(), NOW(), 'system', 'system', 'N'
                ) RETURNING group_id INTO new_group_id;

                -- Insert DEFAULT_GROUP_ID config
                IF new_group_id IS NOT NULL THEN
                    INSERT INTO nexent.tenant_config_t (
                        tenant_id, user_id, value_type, config_key, config_value,
                        create_time, update_time, created_by, updated_by, delete_flag
                    ) VALUES (
                        target_tenant_id, NULL, 'single', 'DEFAULT_GROUP_ID', new_group_id::VARCHAR,
                        NOW(), NOW(), 'system', 'system', 'N'
                    );
                END IF;
            END IF;
        END IF;
    END LOOP;
END $$;
