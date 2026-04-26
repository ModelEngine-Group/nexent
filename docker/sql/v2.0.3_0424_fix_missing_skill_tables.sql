-- Quick fix: Add missing skill-related tables
-- Date: 2026-04-24
-- Description: Add ag_skill_instance_t and related tables for skill functionality

SET search_path TO nexent;

-- Create the ag_skill_info_t table if not exists
CREATE TABLE IF NOT EXISTS nexent.ag_skill_info_t (
    skill_id SERIAL4 PRIMARY KEY NOT NULL,
    skill_name VARCHAR(100) NOT NULL,
    skill_description VARCHAR(1000),
    skill_tags JSON,
    skill_content TEXT,
    params JSON,
    source VARCHAR(30) DEFAULT 'official',
    created_by VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Create the ag_skill_tools_rel_t table if not exists
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

-- Create the ag_skill_instance_t table if not exists
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

-- Add comments
COMMENT ON TABLE nexent.ag_skill_instance_t IS 'Skill instance configuration table - stores per-agent skill settings';
