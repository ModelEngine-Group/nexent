-- Incremental SQL to alter config_value column length in nexent.tenant_config_t table

-- Check if the table exists before attempting to alter it
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'nexent'
        AND table_name = 'tenant_config_t'
    ) THEN
        -- Alter the column length
        EXECUTE 'ALTER TABLE nexent.tenant_config_t ALTER COLUMN config_value TYPE VARCHAR(10000)';

        -- Log the change
        RAISE NOTICE 'Altered config_value column length from VARCHAR(100) to VARCHAR(10000) in nexent.tenant_config_t';
    ELSE
        RAISE NOTICE 'Table nexent.tenant_config_t does not exist, skipping alteration';
    END IF;
END $$;