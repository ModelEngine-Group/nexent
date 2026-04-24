-- v2.0.2_0424_add_prompt_template_t.sql
-- Create prompt template table for tenant-level prompt generation templates.

CREATE TABLE IF NOT EXISTS nexent.ag_prompt_template_t (
    template_id SERIAL4 PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    template_name VARCHAR(100) NOT NULL,
    description VARCHAR(1000),
    template_type VARCHAR(50) DEFAULT 'prompt_generate' NOT NULL,
    content_zh TEXT NOT NULL,
    content_en TEXT NOT NULL,
    source VARCHAR(30) DEFAULT 'custom' NOT NULL,
    created_by VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT uq_prompt_template_tenant_name UNIQUE (tenant_id, template_name)
);

ALTER TABLE nexent.ag_prompt_template_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_prompt_template_t IS 'Prompt template information table - stores tenant-level prompt generation templates.';

COMMENT ON COLUMN nexent.ag_prompt_template_t.template_id IS 'Prompt template ID';
COMMENT ON COLUMN nexent.ag_prompt_template_t.tenant_id IS 'Tenant ID for multi-tenancy isolation';
COMMENT ON COLUMN nexent.ag_prompt_template_t.template_name IS 'Prompt template unique name within a tenant';
COMMENT ON COLUMN nexent.ag_prompt_template_t.description IS 'Prompt template description';
COMMENT ON COLUMN nexent.ag_prompt_template_t.template_type IS 'Template type, currently mainly prompt_generate';
COMMENT ON COLUMN nexent.ag_prompt_template_t.content_zh IS 'Chinese YAML content for the template';
COMMENT ON COLUMN nexent.ag_prompt_template_t.content_en IS 'English YAML content for the template';
COMMENT ON COLUMN nexent.ag_prompt_template_t.source IS 'Template source: builtin, custom';
COMMENT ON COLUMN nexent.ag_prompt_template_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.ag_prompt_template_t.create_time IS 'Creation timestamp';
COMMENT ON COLUMN nexent.ag_prompt_template_t.updated_by IS 'Last updater ID';
COMMENT ON COLUMN nexent.ag_prompt_template_t.update_time IS 'Last update timestamp';
COMMENT ON COLUMN nexent.ag_prompt_template_t.delete_flag IS 'Soft delete flag: Y/N';

CREATE INDEX IF NOT EXISTS idx_ag_prompt_template_t_tenant_type
ON nexent.ag_prompt_template_t (tenant_id, template_type)
WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_ag_prompt_template_t_template_id
ON nexent.ag_prompt_template_t (template_id)
WHERE delete_flag = 'N';
