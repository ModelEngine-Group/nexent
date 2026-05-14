-- Rename params -> config_values, add config_schemas to ag_skill_info_t

ALTER TABLE nexent.ag_skill_info_t ADD COLUMN IF NOT EXISTS config_schemas JSON;

-- Comments for ag_skill_info_t columns
COMMENT ON COLUMN nexent.ag_skill_info_t.config_values IS 'Runtime parameter values from config/config.yaml';
COMMENT ON COLUMN nexent.ag_skill_info_t.config_schemas IS 'Parameter metadata list from config/schema.yaml';

-- Add config_values and config_schemas to ag_skill_instance_t
ALTER TABLE nexent.ag_skill_instance_t ADD COLUMN IF NOT EXISTS config_values JSON;
ALTER TABLE nexent.ag_skill_instance_t ADD COLUMN IF NOT EXISTS config_schemas JSON;

-- Comments for ag_skill_instance_t columns
COMMENT ON COLUMN nexent.ag_skill_instance_t.config_values IS 'Per-agent runtime parameter values from config/config.yaml';
COMMENT ON COLUMN nexent.ag_skill_instance_t.config_schemas IS 'Per-agent parameter schema overrides from config/schema.yaml';
