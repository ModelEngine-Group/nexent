-- Migration: Add ag_skill_info_t, ag_skill_tools_rel_t, and ag_skill_instance_t tables
-- Date: 2026-03-14
-- Description: Create skill management tables with skill content, tags, and tool relationships

SET search_path TO nexent;

-- Create the ag_skill_info_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.ag_skill_info_t (
    skill_id SERIAL4 PRIMARY KEY NOT NULL,
    skill_name VARCHAR(100) NOT NULL,
    skill_description VARCHAR(1000),
    skill_tags JSON,
    skill_content TEXT,
    source VARCHAR(30) DEFAULT 'official',
    created_by VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE "ag_skill_info_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.ag_skill_info_t IS 'Skill information table for managing custom skills';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_id IS 'Skill ID, unique primary key';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_name IS 'Skill name, globally unique';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_description IS 'Skill description text';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_tags IS 'Skill tags stored as JSON array';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_content IS 'Skill content or prompt text';
COMMENT ON COLUMN nexent.ag_skill_info_t.source IS 'Skill source: official, custom, or partner';
COMMENT ON COLUMN nexent.ag_skill_info_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.ag_skill_info_t.create_time IS 'Creation timestamp';
COMMENT ON COLUMN nexent.ag_skill_info_t.updated_by IS 'Last updater ID';
COMMENT ON COLUMN nexent.ag_skill_info_t.update_time IS 'Last update timestamp';
COMMENT ON COLUMN nexent.ag_skill_info_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create the ag_skill_tools_rel_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.ag_skill_tools_rel_t (
    rel_id SERIAL4 PRIMARY KEY NOT NULL,
    skill_id INTEGER,
    tool_id INTEGER,
    created_by VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE "ag_skill_tools_rel_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.ag_skill_tools_rel_t IS 'Skill-tool relationship table for many-to-many mapping';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.rel_id IS 'Relationship ID, unique primary key';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.skill_id IS 'Foreign key to ag_skill_info_t.skill_id';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.tool_id IS 'Tool ID from ag_tool_info_t';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.create_time IS 'Creation timestamp';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.updated_by IS 'Last updater ID';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.update_time IS 'Last update timestamp';
COMMENT ON COLUMN nexent.ag_skill_tools_rel_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create the ag_skill_instance_t table in the nexent schema
-- Stores skill instance configuration per agent version
-- Note: skill_description and skill_content fields removed, now retrieved from ag_skill_info_t
CREATE TABLE IF NOT EXISTS nexent.ag_skill_instance_t (
    skill_instance_id SERIAL4 NOT NULL,
    skill_id INTEGER NOT NULL,
    agent_id INTEGER NOT NULL,
    user_id VARCHAR(100),
    tenant_id VARCHAR(100),
    enabled BOOLEAN DEFAULT TRUE,
    version_no INTEGER DEFAULT 0 NOT NULL,
    created_by VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT ag_skill_instance_t_pkey PRIMARY KEY (skill_instance_id, version_no)
);

ALTER TABLE "ag_skill_instance_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.ag_skill_instance_t IS 'Skill instance configuration table - stores per-agent skill settings';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_skill_instance_t.skill_instance_id IS 'Skill instance ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.skill_id IS 'Foreign key to ag_skill_info_t.skill_id';
COMMENT ON COLUMN nexent.ag_skill_instance_t.agent_id IS 'Agent ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.enabled IS 'Whether this skill is enabled for the agent';
COMMENT ON COLUMN nexent.ag_skill_instance_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';
COMMENT ON COLUMN nexent.ag_skill_instance_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.create_time IS 'Creation timestamp';
COMMENT ON COLUMN nexent.ag_skill_instance_t.updated_by IS 'Last updater ID';
COMMENT ON COLUMN nexent.ag_skill_instance_t.update_time IS 'Last update timestamp';
COMMENT ON COLUMN nexent.ag_skill_instance_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';
