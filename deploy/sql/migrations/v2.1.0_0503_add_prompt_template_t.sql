-- Migration: Add prompt template table and agent prompt template fields
-- Date: 2026-05-03
-- Description: Add user-scoped prompt template storage and bind selected prompt template to agents

ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS prompt_template_id INTEGER;

ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS prompt_template_name VARCHAR(100);

COMMENT ON COLUMN nexent.ag_tenant_agent_t.prompt_template_id IS 'Prompt template ID used for business logic prompt generation';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.prompt_template_name IS 'Prompt template name used for business logic prompt generation';

UPDATE nexent.ag_tenant_agent_t
SET prompt_template_id = 0,
    prompt_template_name = 'system_default'
WHERE delete_flag = 'N'
  AND (prompt_template_id IS NULL OR prompt_template_name IS NULL);

CREATE TABLE IF NOT EXISTS nexent.ag_prompt_template_t (
    template_id SERIAL PRIMARY KEY,
    template_name VARCHAR(100) NOT NULL,
    description VARCHAR(500),
    template_type VARCHAR(50) NOT NULL DEFAULT 'agent_generate',
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    template_content_zh JSONB NOT NULL,
    template_content_en JSONB,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_prompt_template_t OWNER TO "root";

CREATE OR REPLACE FUNCTION update_ag_prompt_template_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_ag_prompt_template_update_time_trigger ON nexent.ag_prompt_template_t;

CREATE TRIGGER update_ag_prompt_template_update_time_trigger
BEFORE UPDATE ON nexent.ag_prompt_template_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_prompt_template_update_time();

ALTER TABLE nexent.ag_prompt_template_t
DROP CONSTRAINT IF EXISTS uq_prompt_template_user_name;

COMMENT ON TABLE nexent.ag_prompt_template_t IS 'Prompt template table for user-defined business logic generation prompts';
COMMENT ON COLUMN nexent.ag_prompt_template_t.template_id IS 'Prompt template ID';
COMMENT ON COLUMN nexent.ag_prompt_template_t.template_name IS 'Prompt template name';
COMMENT ON COLUMN nexent.ag_prompt_template_t.description IS 'Prompt template description';
COMMENT ON COLUMN nexent.ag_prompt_template_t.template_type IS 'Prompt template type';
COMMENT ON COLUMN nexent.ag_prompt_template_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.ag_prompt_template_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.ag_prompt_template_t.template_content_zh IS 'Chinese prompt template content';
COMMENT ON COLUMN nexent.ag_prompt_template_t.template_content_en IS 'English prompt template content';
COMMENT ON COLUMN nexent.ag_prompt_template_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_prompt_template_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_prompt_template_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.ag_prompt_template_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.ag_prompt_template_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

DROP INDEX IF EXISTS nexent.uq_prompt_template_user_name_active;
CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_template_user_name_active
ON nexent.ag_prompt_template_t (tenant_id, user_id, template_name)
WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_ag_prompt_template_t_user
ON nexent.ag_prompt_template_t (tenant_id, user_id, template_type)
WHERE delete_flag = 'N';

INSERT INTO nexent.ag_prompt_template_t (
    template_id,
    template_name,
    description,
    template_type,
    tenant_id,
    user_id,
    template_content_zh,
    template_content_en,
    created_by,
    updated_by,
    delete_flag
)
VALUES (
    0,
    'system_default',
    'System default prompt template',
    'agent_generate',
    'tenant_id',
    'user_id',
    '{}'::jsonb,
    '{}'::jsonb,
    'user_id',
    'user_id',
    'N'
)
ON CONFLICT (template_id) DO UPDATE SET
    template_name = EXCLUDED.template_name,
    description = EXCLUDED.description,
    template_type = EXCLUDED.template_type,
    tenant_id = EXCLUDED.tenant_id,
    user_id = EXCLUDED.user_id,
    template_content_zh = EXCLUDED.template_content_zh,
    template_content_en = EXCLUDED.template_content_en,
    updated_by = EXCLUDED.updated_by,
    delete_flag = 'N';
