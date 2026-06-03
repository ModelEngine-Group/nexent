-- Rename params -> config_values, add config_schemas to ag_skill_info_t
-- Add tenant_id column for multi-tenancy support
ALTER TABLE nexent.ag_skill_info_t ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);

-- Add config_values and config_schemas to ag_skill_info_t
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name   = 'ag_skill_info_t'
          AND column_name  = 'params'
    ) THEN
        ALTER TABLE nexent.ag_skill_info_t RENAME COLUMN params TO config_values;
    END IF;
END $$;
ALTER TABLE nexent.ag_skill_info_t ADD COLUMN IF NOT EXISTS config_schemas JSON;

-- Comments for ag_skill_info_t columns
COMMENT ON COLUMN nexent.ag_skill_info_t.tenant_id IS 'Tenant ID for multi-tenancy. NULL for pre-existing skills.';
COMMENT ON COLUMN nexent.ag_skill_info_t.config_values IS 'Runtime parameter values from config/config.yaml';
COMMENT ON COLUMN nexent.ag_skill_info_t.config_schemas IS 'Parameter metadata list from config/schema.yaml';

-- Add config_values and config_schemas to ag_skill_instance_t
ALTER TABLE nexent.ag_skill_instance_t ADD COLUMN IF NOT EXISTS config_values JSON;
ALTER TABLE nexent.ag_skill_instance_t ADD COLUMN IF NOT EXISTS config_schemas JSON;

-- Comments for ag_skill_instance_t columns
COMMENT ON COLUMN nexent.ag_skill_instance_t.config_values IS 'Per-agent runtime parameter values from config/config.yaml';
COMMENT ON COLUMN nexent.ag_skill_instance_t.config_schemas IS 'Per-agent parameter schema overrides from config/schema.yaml';
