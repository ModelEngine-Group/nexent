-- 1. 为knowledge_record_t表添加knowledge_sources列
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS "knowledge_sources" varchar(100) COLLATE "pg_catalog"."default";

-- 添加列注释
COMMENT ON COLUMN nexent.knowledge_record_t."knowledge_sources" IS 'Knowledge base sources';


-- 2. 创建tenant_config_t表
CREATE TABLE IF NOT EXISTS nexent.tenant_config_t (
    tenant_config_id SERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    value_type VARCHAR(100),
    config_key VARCHAR(100),
    config_value VARCHAR(10000),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- 添加表注释
COMMENT ON TABLE nexent.tenant_config_t IS 'Tenant configuration information table';

-- 添加列注释
COMMENT ON COLUMN nexent.tenant_config_t.tenant_config_id IS 'ID';
COMMENT ON COLUMN nexent.tenant_config_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.tenant_config_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.tenant_config_t.value_type IS 'Value type';
COMMENT ON COLUMN nexent.tenant_config_t.config_key IS 'Config key';
COMMENT ON COLUMN nexent.tenant_config_t.config_value IS 'Config value';
COMMENT ON COLUMN nexent.tenant_config_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.tenant_config_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.tenant_config_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.tenant_config_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.tenant_config_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- 创建更新update_time的函数
CREATE OR REPLACE FUNCTION update_tenant_config_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 添加函数注释
COMMENT ON FUNCTION update_tenant_config_update_time() IS 'Function to update the update_time column when a record in tenant_config_t is updated';

-- 创建触发器
DROP TRIGGER IF EXISTS update_tenant_config_update_time_trigger ON nexent.tenant_config_t;
CREATE TRIGGER update_tenant_config_update_time_trigger
BEFORE UPDATE ON nexent.tenant_config_t
FOR EACH ROW
EXECUTE FUNCTION update_tenant_config_update_time();

-- 添加触发器注释
COMMENT ON TRIGGER update_tenant_config_update_time_trigger ON nexent.tenant_config_t
IS 'Trigger to call update_tenant_config_update_time function before each update on tenant_config_t table';

ALTER TABLE model_record_t
ADD COLUMN IF NOT EXISTS tenant_id varchar(100) COLLATE pg_catalog.default DEFAULT 'tenant_id';
COMMENT ON COLUMN "model_record_t"."tenant_id" IS 'Tenant ID for filtering';-- Incremental SQL to alter config_value column length in nexent.tenant_config_t table

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
END $$;-- Migration: Add mcp_record_t table
-- Date: 2024-06-30
-- Description: Create MCP (Model Context Protocol) records table with audit fields

-- Set search path to nexent schema
SET search_path TO nexent;

-- Create the mcp_record_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.mcp_record_t (
    mcp_id SERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    mcp_name VARCHAR(100),
    mcp_server VARCHAR(500),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE "mcp_record_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.mcp_record_t IS 'MCP (Model Context Protocol) records table';

-- Add comments to the columns
COMMENT ON COLUMN nexent.mcp_record_t.mcp_id IS 'MCP record ID, unique primary key';
COMMENT ON COLUMN nexent.mcp_record_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.mcp_record_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.mcp_record_t.mcp_name IS 'MCP name';
COMMENT ON COLUMN nexent.mcp_record_t.mcp_server IS 'MCP server address';
COMMENT ON COLUMN nexent.mcp_record_t.create_time IS 'Creation time, audit field';
COMMENT ON COLUMN nexent.mcp_record_t.update_time IS 'Update time, audit field';
COMMENT ON COLUMN nexent.mcp_record_t.created_by IS 'Creator ID, audit field';
COMMENT ON COLUMN nexent.mcp_record_t.updated_by IS 'Last updater ID, audit field';
COMMENT ON COLUMN nexent.mcp_record_t.delete_flag IS 'When deleted by user frontend, delete flag will be set to true, achieving soft delete effect. Optional values Y/N';

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_mcp_record_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add comment to the function
COMMENT ON FUNCTION update_mcp_record_update_time() IS 'Function to update the update_time column when a record in mcp_record_t is updated';

-- Create a trigger to call the function before each update
DROP TRIGGER IF EXISTS update_mcp_record_update_time_trigger ON nexent.mcp_record_t;
CREATE TRIGGER update_mcp_record_update_time_trigger
BEFORE UPDATE ON nexent.mcp_record_t
FOR EACH ROW
EXECUTE FUNCTION update_mcp_record_update_time();

-- Add comment to the trigger
COMMENT ON TRIGGER update_mcp_record_update_time_trigger ON nexent.mcp_record_t IS 'Trigger to call update_mcp_record_update_time function before each update on mcp_record_t table';
-- Create user tenant relationship table
CREATE TABLE IF NOT EXISTS nexent.user_tenant_t (
    user_tenant_id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag CHAR(1) DEFAULT 'N',
    UNIQUE(user_id, tenant_id)
);

-- Add comment
COMMENT ON TABLE nexent.user_tenant_t IS 'User tenant relationship table';
COMMENT ON COLUMN nexent.user_tenant_t.user_tenant_id IS 'User tenant relationship ID, primary key';
COMMENT ON COLUMN nexent.user_tenant_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.user_tenant_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.user_tenant_t.create_time IS 'Create time';
COMMENT ON COLUMN nexent.user_tenant_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.user_tenant_t.created_by IS 'Created by';
COMMENT ON COLUMN nexent.user_tenant_t.updated_by IS 'Updated by';
COMMENT ON COLUMN nexent.user_tenant_t.delete_flag IS 'Delete flag, Y/N'; ALTER TABLE nexent.knowledge_record_t
  ALTER COLUMN knowledge_describe TYPE varchar(3000);ALTER TABLE nexent.mcp_record_t
ADD COLUMN IF NOT EXISTS status BOOLEAN DEFAULT NULL;
COMMENT ON COLUMN nexent.mcp_record_t.status IS 'MCP server connection status, true=connected, false=disconnected, null=unknown'; -- Migration script to add new prompt fields to ag_tenant_agent_t table
-- Add three new columns for storing segmented prompt content

-- Add duty_prompt column
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS duty_prompt TEXT;

-- Add constraint_prompt column
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS constraint_prompt TEXT;

-- Add few_shots_prompt column
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS few_shots_prompt TEXT;

-- Drop prompt column
ALTER TABLE nexent.ag_tenant_agent_t
DROP COLUMN IF EXISTS prompt;

-- Add comments to the new columns
COMMENT ON COLUMN nexent.ag_tenant_agent_t.duty_prompt IS 'Duty prompt content';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.constraint_prompt IS 'Constraint prompt content';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.few_shots_prompt IS 'Few shots prompt content';-- Migration script to add ag_agent_relation_t table for recording agent parent-child relationships
-- This table is used to store the hierarchical relationships between agents

-- Create the ag_agent_relation_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.ag_agent_relation_t (
    relation_id SERIAL PRIMARY KEY NOT NULL,
    selected_agent_id INTEGER,
    parent_agent_id INTEGER,
    tenant_id VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_ag_agent_relation_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create a trigger to call the function before each update
DROP TRIGGER IF EXISTS update_ag_agent_relation_update_time_trigger ON nexent.ag_agent_relation_t;
CREATE TRIGGER update_ag_agent_relation_update_time_trigger
BEFORE UPDATE ON nexent.ag_agent_relation_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_agent_relation_update_time();

-- Add comment to the table
COMMENT ON TABLE nexent.ag_agent_relation_t IS 'Agent parent-child relationship table';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_agent_relation_t.relation_id IS 'Relationship ID, primary key';
COMMENT ON COLUMN nexent.ag_agent_relation_t.selected_agent_id IS 'Selected agent ID';
COMMENT ON COLUMN nexent.ag_agent_relation_t.parent_agent_id IS 'Parent agent ID';
COMMENT ON COLUMN nexent.ag_agent_relation_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.ag_agent_relation_t.create_time IS 'Creation time, audit field';
COMMENT ON COLUMN nexent.ag_agent_relation_t.update_time IS 'Update time, audit field';
COMMENT ON COLUMN nexent.ag_agent_relation_t.created_by IS 'Creator ID, audit field';
COMMENT ON COLUMN nexent.ag_agent_relation_t.updated_by IS 'Last updater ID, audit field';
COMMENT ON COLUMN nexent.ag_agent_relation_t.delete_flag IS 'Delete flag, set to Y for soft delete, optional values Y/N'; ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS is_deep_thinking BOOLEAN DEFAULT FALSE;
COMMENT ON COLUMN nexent.model_record_t.is_deep_thinking IS 'deep thinking switch, true=open, false=close';-- 创建序列
CREATE SEQUENCE IF NOT EXISTS "nexent"."memory_user_config_t_config_id_seq"
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;


-- 创建表
CREATE TABLE IF NOT EXISTS "nexent"."memory_user_config_t" (
  "config_id" SERIAL PRIMARY KEY NOT NULL,
  "tenant_id" varchar(100) COLLATE "pg_catalog"."default",
  "user_id" varchar(100) COLLATE "pg_catalog"."default",
  "value_type" varchar(100) COLLATE "pg_catalog"."default",
  "config_key" varchar(100) COLLATE "pg_catalog"."default",
  "config_value" varchar(100) COLLATE "pg_catalog"."default",
  "create_time" timestamp(6) DEFAULT CURRENT_TIMESTAMP,
  "update_time" timestamp(6) DEFAULT CURRENT_TIMESTAMP,
  "created_by" varchar(100) COLLATE "pg_catalog"."default",
  "updated_by" varchar(100) COLLATE "pg_catalog"."default",
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'::character varying
);

-- 设置表所有者
ALTER TABLE "nexent"."memory_user_config_t" OWNER TO "root";

COMMENT ON COLUMN "nexent"."memory_user_config_t"."config_id" IS 'ID';
COMMENT ON COLUMN "nexent"."memory_user_config_t"."tenant_id" IS 'Tenant ID';
COMMENT ON COLUMN "nexent"."memory_user_config_t"."user_id" IS 'User ID';
COMMENT ON COLUMN "nexent"."memory_user_config_t"."value_type" IS 'Value type. Optional values: single/multi';
COMMENT ON COLUMN "nexent"."memory_user_config_t"."config_key" IS 'Config key';
COMMENT ON COLUMN "nexent"."memory_user_config_t"."config_value" IS 'Config value';
COMMENT ON COLUMN "nexent"."memory_user_config_t"."create_time" IS 'Creation time';
COMMENT ON COLUMN "nexent"."memory_user_config_t"."update_time" IS 'Update time';
COMMENT ON COLUMN "nexent"."memory_user_config_t"."created_by" IS 'Creator';
COMMENT ON COLUMN "nexent"."memory_user_config_t"."updated_by" IS 'Updater';
COMMENT ON COLUMN "nexent"."memory_user_config_t"."delete_flag" IS 'Whether it is deleted. Optional values: Y/N';

COMMENT ON TABLE "nexent"."memory_user_config_t" IS 'User configuration of memory setting table';

CREATE OR REPLACE FUNCTION "update_memory_user_config_update_time"()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS "update_memory_user_config_update_time_trigger" ON "nexent"."memory_user_config_t";
CREATE TRIGGER "update_memory_user_config_update_time_trigger"
BEFORE UPDATE ON "nexent"."memory_user_config_t"
FOR EACH ROW
EXECUTE FUNCTION "update_memory_user_config_update_time"();CREATE SEQUENCE IF NOT EXISTS "nexent"."partner_mapping_id_t_mapping_id_seq"
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

CREATE TABLE IF NOT EXISTS "nexent"."partner_mapping_id_t" (
  "mapping_id" serial PRIMARY KEY NOT NULL,
  "external_id" varchar(100) COLLATE "pg_catalog"."default",
  "internal_id" int4,
  "mapping_type" varchar(30) COLLATE "pg_catalog"."default",
  "tenant_id" varchar(100) COLLATE "pg_catalog"."default",
  "user_id" varchar(100) COLLATE "pg_catalog"."default",
  "create_time" timestamp(6) DEFAULT CURRENT_TIMESTAMP,
  "update_time" timestamp(6) DEFAULT CURRENT_TIMESTAMP,
  "created_by" varchar(100) COLLATE "pg_catalog"."default",
  "updated_by" varchar(100) COLLATE "pg_catalog"."default",
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'::character varying
);

ALTER TABLE "nexent"."partner_mapping_id_t" OWNER TO "root";

COMMENT ON COLUMN "nexent"."partner_mapping_id_t"."mapping_id" IS 'ID';
COMMENT ON COLUMN "nexent"."partner_mapping_id_t"."external_id" IS 'The external id given by the outer partner';
COMMENT ON COLUMN "nexent"."partner_mapping_id_t"."internal_id" IS 'The internal id of the other database table';
COMMENT ON COLUMN "nexent"."partner_mapping_id_t"."mapping_type" IS 'Type of the external - internal mapping, value set: CONVERSATION';
COMMENT ON COLUMN "nexent"."partner_mapping_id_t"."tenant_id" IS 'Tenant ID';
COMMENT ON COLUMN "nexent"."partner_mapping_id_t"."user_id" IS 'User ID';
COMMENT ON COLUMN "nexent"."partner_mapping_id_t"."create_time" IS 'Creation time';
COMMENT ON COLUMN "nexent"."partner_mapping_id_t"."update_time" IS 'Update time';
COMMENT ON COLUMN "nexent"."partner_mapping_id_t"."created_by" IS 'Creator';
COMMENT ON COLUMN "nexent"."partner_mapping_id_t"."updated_by" IS 'Updater';
COMMENT ON COLUMN "nexent"."partner_mapping_id_t"."delete_flag" IS 'Whether it is deleted. Optional values: Y/N';

CREATE OR REPLACE FUNCTION "update_partner_mapping_update_time"()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS "update_partner_mapping_update_time_trigger" ON "nexent"."partner_mapping_id_t";
CREATE TRIGGER "update_partner_mapping_update_time_trigger"
BEFORE UPDATE ON "nexent"."partner_mapping_id_t"
FOR EACH ROW
EXECUTE FUNCTION "update_partner_mapping_update_time"();ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS display_name VARCHAR(100);
COMMENT ON COLUMN nexent.ag_tenant_agent_t.display_name IS 'Agent展示名称';ALTER TABLE nexent.model_record_t
DROP COLUMN IF EXISTS is_deep_thinking;-- Add model_name column to knowledge_record_t table, used to record the embedding model used by the knowledge base

-- Switch to nexent schema
SET search_path TO nexent;

-- Add model_name column
ALTER TABLE "knowledge_record_t"
ADD COLUMN IF NOT EXISTS "embedding_model_name" varchar(200) COLLATE "pg_catalog"."default";

-- Add column comment
COMMENT ON COLUMN "knowledge_record_t"."embedding_model_name" IS 'Embedding model name, used to record the embedding model used by the knowledge base';-- Add origin_name column to ag_tool_info_t table
-- This field stores the original tool name before any transformations

ALTER TABLE nexent.ag_tool_info_t
ADD COLUMN IF NOT EXISTS origin_name VARCHAR(100);

-- Add comment to document the purpose of this field
COMMENT ON COLUMN nexent.ag_tool_info_t.origin_name IS 'Original tool name before any transformations or mappings';
-- Add category column to ag_tool_info_t table
-- This field stores the tool category information (search, file, email, terminal)

ALTER TABLE nexent.ag_tool_info_t
ADD COLUMN IF NOT EXISTS category VARCHAR(100);

-- Add comment to document the purpose of this field
COMMENT ON COLUMN nexent.ag_tool_info_t.category IS 'Tool category information';
-- Add model_id column to ag_tenant_agent_t table and deprecate model_name field
-- Date: 2024-09-28
-- Description: Add model_id field to ag_tenant_agent_t table and mark model_name as deprecated

-- Switch to the nexent schema
SET search_path TO nexent;

-- Add model_id column to ag_tenant_agent_t table
ALTER TABLE ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS model_id INTEGER;

-- Add comment for the new model_id column
COMMENT ON COLUMN ag_tenant_agent_t.model_id IS 'Model ID, foreign key reference to model_record_t.model_id';

-- Update comment for model_name column to mark it as deprecated
COMMENT ON COLUMN ag_tenant_agent_t.model_name IS '[DEPRECATED] Name of the model used, use model_id instead';

-- Optional: Add foreign key constraint (uncomment if needed)
-- ALTER TABLE ag_tenant_agent_t
-- ADD CONSTRAINT fk_ag_tenant_agent_model_id
-- FOREIGN KEY (model_id) REFERENCES model_record_t(model_id);
ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS expected_chunk_size INT4,
ADD COLUMN IF NOT EXISTS maximum_chunk_size INT4;

COMMENT ON COLUMN nexent.model_record_t.expected_chunk_size IS 'Expected chunk size for embedding models, used during document chunking';
COMMENT ON COLUMN nexent.model_record_t.maximum_chunk_size IS 'Maximum chunk size for embedding models, used during document chunking';

-- Add business_logic_model_name and business_logic_model_id fields to ag_tenant_agent_t table
-- These fields store the LLM model used for generating business logic prompts

ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS business_logic_model_name VARCHAR(100);

ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS business_logic_model_id INTEGER;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.business_logic_model_name IS 'Model name used for business logic prompt generation';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.business_logic_model_id IS 'Model ID used for business logic prompt generation, foreign key reference to model_record_t.model_id';

ALTER TABLE nexent.tenant_config_t ALTER COLUMN config_value TYPE TEXT;ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS ssl_verify BOOLEAN DEFAULT TRUE;

COMMENT ON COLUMN nexent.model_record_t.ssl_verify IS 'Whether to verify SSL certificates when connecting to this model API. Default is true. Set to false for local services without SSL support.';

-- Add knowledge_name column if it does not exist
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS knowledge_name varchar(100) COLLATE "pg_catalog"."default";

COMMENT ON COLUMN nexent.knowledge_record_t.knowledge_name IS 'User-facing knowledge base name (display name), mapped to internal index_name';
COMMENT ON COLUMN nexent.knowledge_record_t.index_name IS 'Internal Elasticsearch index name';

-- Backfill existing records: for legacy data, use index_name as knowledge_name
UPDATE nexent.knowledge_record_t
SET knowledge_name = index_name
WHERE knowledge_name IS NULL;


-- Add chunk_batch column in model_record_t table
ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS chunk_batch INT4;

COMMENT ON COLUMN nexent.model_record_t.chunk_batch IS 'Batch size for concurrent embedding requests during document chunking';-- Add author column to ag_tenant_agent_t table
-- This migration adds the author field to support agent author information

-- Add author column with default NULL value for backward compatibility
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS author VARCHAR(100);

-- Add comment to the column
COMMENT ON COLUMN nexent.ag_tenant_agent_t.author IS 'Agent author';

-- Add invitation code and group management system
-- This migration adds invitation codes, groups, and permission management features

-- 1. Create tenant_invitation_code_t table for invitation codes
CREATE TABLE IF NOT EXISTS nexent.tenant_invitation_code_t (
    invitation_id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    invitation_code VARCHAR(100) NOT NULL,
    group_ids VARCHAR, -- int4 list
    capacity INT4 NOT NULL DEFAULT 1,
    expiry_date TIMESTAMP(6) WITHOUT TIME ZONE,
    status VARCHAR(30) NOT NULL,
    code_type VARCHAR(30) NOT NULL,
    create_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    update_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Add comments for tenant_invitation_code_t table
COMMENT ON TABLE nexent.tenant_invitation_code_t IS 'Tenant invitation code information table';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.invitation_id IS 'Invitation ID, primary key';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.tenant_id IS 'Tenant ID, foreign key';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.invitation_code IS 'Invitation code';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.group_ids IS 'Associated group IDs list';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.capacity IS 'Invitation code capacity';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.expiry_date IS 'Invitation code expiry date';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.status IS 'Invitation code status: IN_USE, EXPIRE, DISABLE, RUN_OUT';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.code_type IS 'Invitation code type: ADMIN_INVITE, DEV_INVITE, USER_INVITE';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.create_time IS 'Create time';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.created_by IS 'Created by';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.updated_by IS 'Updated by';
COMMENT ON COLUMN nexent.tenant_invitation_code_t.delete_flag IS 'Delete flag, Y/N';

-- 2. Create tenant_invitation_record_t table for invitation usage records
CREATE TABLE IF NOT EXISTS nexent.tenant_invitation_record_t (
    invitation_record_id SERIAL PRIMARY KEY,
    invitation_id INT4 NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    create_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    update_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Add comments for tenant_invitation_record_t table
COMMENT ON TABLE nexent.tenant_invitation_record_t IS 'Tenant invitation record table';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.invitation_record_id IS 'Invitation record ID, primary key';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.invitation_id IS 'Invitation ID, foreign key';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.create_time IS 'Create time';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.created_by IS 'Created by';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.updated_by IS 'Updated by';
COMMENT ON COLUMN nexent.tenant_invitation_record_t.delete_flag IS 'Delete flag, Y/N';

-- 3. Create tenant_group_info_t table for group information
CREATE TABLE IF NOT EXISTS nexent.tenant_group_info_t (
    group_id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_description VARCHAR(500),
    create_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    update_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Add comments for tenant_group_info_t table
COMMENT ON TABLE nexent.tenant_group_info_t IS 'Tenant group information table';
COMMENT ON COLUMN nexent.tenant_group_info_t.group_id IS 'Group ID, primary key';
COMMENT ON COLUMN nexent.tenant_group_info_t.tenant_id IS 'Tenant ID, foreign key';
COMMENT ON COLUMN nexent.tenant_group_info_t.group_name IS 'Group name';
COMMENT ON COLUMN nexent.tenant_group_info_t.group_description IS 'Group description';
COMMENT ON COLUMN nexent.tenant_group_info_t.create_time IS 'Create time';
COMMENT ON COLUMN nexent.tenant_group_info_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.tenant_group_info_t.created_by IS 'Created by';
COMMENT ON COLUMN nexent.tenant_group_info_t.updated_by IS 'Updated by';
COMMENT ON COLUMN nexent.tenant_group_info_t.delete_flag IS 'Delete flag, Y/N';

-- 4. Create tenant_group_user_t table for group user membership
CREATE TABLE IF NOT EXISTS nexent.tenant_group_user_t (
    group_user_id SERIAL PRIMARY KEY,
    group_id INT4 NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    create_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    update_time TIMESTAMP(6) WITHOUT TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Add comments for tenant_group_user_t table
COMMENT ON TABLE nexent.tenant_group_user_t IS 'Tenant group user membership table';
COMMENT ON COLUMN nexent.tenant_group_user_t.group_user_id IS 'Group user ID, primary key';
COMMENT ON COLUMN nexent.tenant_group_user_t.group_id IS 'Group ID, foreign key';
COMMENT ON COLUMN nexent.tenant_group_user_t.user_id IS 'User ID, foreign key';
COMMENT ON COLUMN nexent.tenant_group_user_t.create_time IS 'Create time';
COMMENT ON COLUMN nexent.tenant_group_user_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.tenant_group_user_t.created_by IS 'Created by';
COMMENT ON COLUMN nexent.tenant_group_user_t.updated_by IS 'Updated by';
COMMENT ON COLUMN nexent.tenant_group_user_t.delete_flag IS 'Delete flag, Y/N';

-- 5. Add fields to user_tenant_t table
ALTER TABLE nexent.user_tenant_t
ADD COLUMN IF NOT EXISTS user_role VARCHAR(30);

-- Add comments for new fields in user_tenant_t table
COMMENT ON COLUMN nexent.user_tenant_t.user_role IS 'User role: SU, ADMIN, DEV, USER';

-- 6. Create role_permission_t table for role permissions
CREATE TABLE IF NOT EXISTS nexent.role_permission_t (
    role_permission_id SERIAL PRIMARY KEY,
    user_role VARCHAR(30) NOT NULL,
    permission_category VARCHAR(30),
    permission_type VARCHAR(30),
    permission_subtype VARCHAR(30)
);

-- Add comments for role_permission_t table
COMMENT ON TABLE nexent.role_permission_t IS 'Role permission configuration table';
COMMENT ON COLUMN nexent.role_permission_t.role_permission_id IS 'Role permission ID, primary key';
COMMENT ON COLUMN nexent.role_permission_t.user_role IS 'User role: SU, ADMIN, DEV, USER';
COMMENT ON COLUMN nexent.role_permission_t.permission_category IS 'Permission category';
COMMENT ON COLUMN nexent.role_permission_t.permission_type IS 'Permission type';
COMMENT ON COLUMN nexent.role_permission_t.permission_subtype IS 'Permission subtype';

-- 7. Add fields to knowledge_record_t table
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS group_ids VARCHAR, -- int4 list
ADD COLUMN IF NOT EXISTS ingroup_permission VARCHAR(30);

-- Add comments for new fields in knowledge_record_t table
COMMENT ON COLUMN nexent.knowledge_record_t.group_ids IS 'Knowledge base group IDs list';
COMMENT ON COLUMN nexent.knowledge_record_t.ingroup_permission IS 'In-group permission: EDIT, READ_ONLY, PRIVATE';

-- 8. Add fields to ag_tenant_agent_t table
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS group_ids VARCHAR; -- int4 list

-- Add comments for new fields in ag_tenant_agent_t table
COMMENT ON COLUMN nexent.ag_tenant_agent_t.group_ids IS 'Agent group IDs list';

-- 9. Insert role permission data
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(2, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(3, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(4, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(5, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(6, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(7, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(8, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(9, 'SU', 'RESOURCE', 'AGENT', 'READ'),
(10, 'SU', 'RESOURCE', 'AGENT', 'DELETE'),
(11, 'SU', 'RESOURCE', 'KB', 'READ'),
(12, 'SU', 'RESOURCE', 'KB', 'DELETE'),
(13, 'SU', 'RESOURCE', 'KB.GROUPS', 'READ'),
(14, 'SU', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(15, 'SU', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(16, 'SU', 'RESOURCE', 'USER.ROLE', 'READ'),
(17, 'SU', 'RESOURCE', 'USER.ROLE', 'UPDATE'),
(18, 'SU', 'RESOURCE', 'USER.ROLE', 'DELETE'),
(19, 'SU', 'RESOURCE', 'MCP', 'READ'),
(20, 'SU', 'RESOURCE', 'MCP', 'DELETE'),
(21, 'SU', 'RESOURCE', 'MEM.SETTING', 'READ'),
(22, 'SU', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(23, 'SU', 'RESOURCE', 'MEM.AGENT', 'READ'),
(24, 'SU', 'RESOURCE', 'MEM.AGENT', 'DELETE'),
(25, 'SU', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(26, 'SU', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(27, 'SU', 'RESOURCE', 'MODEL', 'CREATE'),
(28, 'SU', 'RESOURCE', 'MODEL', 'READ'),
(29, 'SU', 'RESOURCE', 'MODEL', 'UPDATE'),
(30, 'SU', 'RESOURCE', 'MODEL', 'DELETE'),
(31, 'SU', 'RESOURCE', 'TENANT', 'CREATE'),
(32, 'SU', 'RESOURCE', 'TENANT', 'READ'),
(33, 'SU', 'RESOURCE', 'TENANT', 'UPDATE'),
(34, 'SU', 'RESOURCE', 'TENANT', 'DELETE'),
(35, 'SU', 'RESOURCE', 'TENANT.INFO', 'READ'),
(36, 'SU', 'RESOURCE', 'TENANT.INFO', 'UPDATE'),
(37, 'SU', 'RESOURCE', 'TENANT.INVITE', 'CREATE'),
(38, 'SU', 'RESOURCE', 'TENANT.INVITE', 'READ'),
(39, 'SU', 'RESOURCE', 'TENANT.INVITE', 'UPDATE'),
(40, 'SU', 'RESOURCE', 'TENANT.INVITE', 'DELETE'),
(41, 'SU', 'RESOURCE', 'GROUP', 'CREATE'),
(42, 'SU', 'RESOURCE', 'GROUP', 'READ'),
(43, 'SU', 'RESOURCE', 'GROUP', 'UPDATE'),
(44, 'SU', 'RESOURCE', 'GROUP', 'DELETE'),
(45, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(46, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(47, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/setup'),
(48, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(49, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/market'),
(50, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents'),
(51, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(52, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(53, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(54, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(55, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(56, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(57, 'ADMIN', 'RESOURCE', 'AGENT', 'CREATE'),
(58, 'ADMIN', 'RESOURCE', 'AGENT', 'READ'),
(59, 'ADMIN', 'RESOURCE', 'AGENT', 'UPDATE'),
(60, 'ADMIN', 'RESOURCE', 'AGENT', 'DELETE'),
(61, 'ADMIN', 'RESOURCE', 'KB', 'CREATE'),
(62, 'ADMIN', 'RESOURCE', 'KB', 'READ'),
(63, 'ADMIN', 'RESOURCE', 'KB', 'UPDATE'),
(64, 'ADMIN', 'RESOURCE', 'KB', 'DELETE'),
(65, 'ADMIN', 'RESOURCE', 'KB.GROUPS', 'READ'),
(66, 'ADMIN', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(67, 'ADMIN', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(68, 'ADMIN', 'RESOURCE', 'USER.ROLE', 'READ'),
(69, 'ADMIN', 'RESOURCE', 'MCP', 'CREATE'),
(70, 'ADMIN', 'RESOURCE', 'MCP', 'READ'),
(71, 'ADMIN', 'RESOURCE', 'MCP', 'UPDATE'),
(72, 'ADMIN', 'RESOURCE', 'MCP', 'DELETE'),
(73, 'ADMIN', 'RESOURCE', 'MEM.SETTING', 'READ'),
(74, 'ADMIN', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(75, 'ADMIN', 'RESOURCE', 'MEM.AGENT', 'CREATE'),
(76, 'ADMIN', 'RESOURCE', 'MEM.AGENT', 'READ'),
(77, 'ADMIN', 'RESOURCE', 'MEM.AGENT', 'DELETE'),
(78, 'ADMIN', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(79, 'ADMIN', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(80, 'ADMIN', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(81, 'ADMIN', 'RESOURCE', 'MODEL', 'CREATE'),
(82, 'ADMIN', 'RESOURCE', 'MODEL', 'READ'),
(83, 'ADMIN', 'RESOURCE', 'MODEL', 'UPDATE'),
(84, 'ADMIN', 'RESOURCE', 'MODEL', 'DELETE'),
(85, 'ADMIN', 'RESOURCE', 'TENANT.INFO', 'READ'),
(86, 'ADMIN', 'RESOURCE', 'TENANT.INFO', 'UPDATE'),
(87, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'CREATE'),
(88, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'READ'),
(89, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'UPDATE'),
(90, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'DELETE'),
(91, 'ADMIN', 'RESOURCE', 'GROUP', 'CREATE'),
(92, 'ADMIN', 'RESOURCE', 'GROUP', 'READ'),
(93, 'ADMIN', 'RESOURCE', 'GROUP', 'UPDATE'),
(94, 'ADMIN', 'RESOURCE', 'GROUP', 'DELETE'),
(95, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(96, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(97, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/setup'),
(98, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(99, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/market'),
(100, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents'),
(101, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(102, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(103, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(104, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(105, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(106, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(107, 'DEV', 'RESOURCE', 'AGENT', 'CREATE'),
(108, 'DEV', 'RESOURCE', 'AGENT', 'READ'),
(109, 'DEV', 'RESOURCE', 'AGENT', 'UPDATE'),
(110, 'DEV', 'RESOURCE', 'AGENT', 'DELETE'),
(111, 'DEV', 'RESOURCE', 'KB', 'CREATE'),
(112, 'DEV', 'RESOURCE', 'KB', 'READ'),
(113, 'DEV', 'RESOURCE', 'KB', 'UPDATE'),
(114, 'DEV', 'RESOURCE', 'KB', 'DELETE'),
(115, 'DEV', 'RESOURCE', 'KB.GROUPS', 'READ'),
(116, 'DEV', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(117, 'DEV', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(118, 'DEV', 'RESOURCE', 'USER.ROLE', 'READ'),
(119, 'DEV', 'RESOURCE', 'MCP', 'CREATE'),
(120, 'DEV', 'RESOURCE', 'MCP', 'READ'),
(121, 'DEV', 'RESOURCE', 'MCP', 'UPDATE'),
(122, 'DEV', 'RESOURCE', 'MCP', 'DELETE'),
(123, 'DEV', 'RESOURCE', 'MEM.SETTING', 'READ'),
(124, 'DEV', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(125, 'DEV', 'RESOURCE', 'MEM.AGENT', 'READ'),
(126, 'DEV', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(127, 'DEV', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(128, 'DEV', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(129, 'DEV', 'RESOURCE', 'MODEL', 'READ'),
(130, 'DEV', 'RESOURCE', 'TENANT.INFO', 'READ'),
(131, 'DEV', 'RESOURCE', 'GROUP', 'READ'),
(132, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(133, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(134, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(135, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(136, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(137, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(138, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(139, 'USER', 'RESOURCE', 'AGENT', 'READ'),
(140, 'USER', 'RESOURCE', 'KB', 'CREATE'),
(141, 'USER', 'RESOURCE', 'KB', 'READ'),
(142, 'USER', 'RESOURCE', 'KB', 'UPDATE'),
(143, 'USER', 'RESOURCE', 'KB', 'DELETE'),
(144, 'USER', 'RESOURCE', 'KB.GROUPS', 'READ'),
(145, 'USER', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(146, 'USER', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(147, 'USER', 'RESOURCE', 'USER.ROLE', 'READ'),
(148, 'USER', 'RESOURCE', 'MCP', 'CREATE'),
(149, 'USER', 'RESOURCE', 'MCP', 'READ'),
(150, 'USER', 'RESOURCE', 'MCP', 'UPDATE'),
(151, 'USER', 'RESOURCE', 'MCP', 'DELETE'),
(152, 'USER', 'RESOURCE', 'MEM.SETTING', 'READ'),
(153, 'USER', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(154, 'USER', 'RESOURCE', 'MEM.AGENT', 'READ'),
(155, 'USER', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(156, 'USER', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(157, 'USER', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(158, 'USER', 'RESOURCE', 'MODEL', 'READ'),
(159, 'USER', 'RESOURCE', 'TENANT.INFO', 'READ'),
(160, 'USER', 'RESOURCE', 'GROUP', 'READ'),
(161, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(162, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(163, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/setup'),
(164, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(165, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/market'),
(166, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents'),
(167, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(168, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(169, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(170, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(171, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(172, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(173, 'SPEED', 'RESOURCE', 'AGENT', 'CREATE'),
(174, 'SPEED', 'RESOURCE', 'AGENT', 'READ'),
(175, 'SPEED', 'RESOURCE', 'AGENT', 'UPDATE'),
(176, 'SPEED', 'RESOURCE', 'AGENT', 'DELETE'),
(177, 'SPEED', 'RESOURCE', 'KB', 'CREATE'),
(178, 'SPEED', 'RESOURCE', 'KB', 'READ'),
(179, 'SPEED', 'RESOURCE', 'KB', 'UPDATE'),
(180, 'SPEED', 'RESOURCE', 'KB', 'DELETE'),
(181, 'SPEED', 'RESOURCE', 'KB.GROUPS', 'READ'),
(182, 'SPEED', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(183, 'SPEED', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(184, 'SPEED', 'RESOURCE', 'USER.ROLE', 'READ'),
(185, 'SPEED', 'RESOURCE', 'MCP', 'CREATE'),
(186, 'SPEED', 'RESOURCE', 'MCP', 'READ'),
(187, 'SPEED', 'RESOURCE', 'MCP', 'UPDATE'),
(188, 'SPEED', 'RESOURCE', 'MCP', 'DELETE'),
(189, 'SPEED', 'RESOURCE', 'MEM.SETTING', 'READ'),
(190, 'SPEED', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(191, 'SPEED', 'RESOURCE', 'MEM.AGENT', 'CREATE'),
(192, 'SPEED', 'RESOURCE', 'MEM.AGENT', 'READ'),
(193, 'SPEED', 'RESOURCE', 'MEM.AGENT', 'DELETE'),
(194, 'SPEED', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(195, 'SPEED', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(196, 'SPEED', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(197, 'SPEED', 'RESOURCE', 'MODEL', 'CREATE'),
(198, 'SPEED', 'RESOURCE', 'MODEL', 'READ'),
(199, 'SPEED', 'RESOURCE', 'MODEL', 'UPDATE'),
(200, 'SPEED', 'RESOURCE', 'MODEL', 'DELETE'),
(201, 'SPEED', 'RESOURCE', 'TENANT.INFO', 'READ'),
(202, 'SPEED', 'RESOURCE', 'TENANT.INFO', 'UPDATE'),
(203, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'CREATE'),
(204, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'READ'),
(205, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'UPDATE'),
(206, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'DELETE'),
(207, 'SPEED', 'RESOURCE', 'GROUP', 'CREATE'),
(208, 'SPEED', 'RESOURCE', 'GROUP', 'READ'),
(209, 'SPEED', 'RESOURCE', 'GROUP', 'UPDATE'),
(210, 'SPEED', 'RESOURCE', 'GROUP', 'DELETE')
ON CONFLICT (role_permission_id) DO NOTHING;
-- Add is_new column to ag_tenant_agent_t table for new agent marking
-- This migration adds a field to track whether an agent is marked as new for users

-- Add is_new column with default value false
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS is_new BOOLEAN DEFAULT FALSE;

-- Add comment for the new column
COMMENT ON COLUMN nexent.ag_tenant_agent_t.is_new IS 'Whether this agent is marked as new for the user';

-- Create index for performance on is_new queries
CREATE INDEX IF NOT EXISTS idx_ag_tenant_agent_t_is_new
ON nexent.ag_tenant_agent_t (tenant_id, is_new)
WHERE delete_flag = 'N';


-- Add user_email column to user_tenant_t table
ALTER TABLE nexent.user_tenant_t
ADD COLUMN IF NOT EXISTS user_email VARCHAR(255);

-- Add comment to the new column
COMMENT ON COLUMN nexent.user_tenant_t.user_email IS 'User email address';

INSERT INTO nexent.user_tenant_t (user_id, tenant_id, user_role, user_email, created_by, updated_by)
VALUES ('user_id', 'tenant_id', 'SPEED', NULL, 'system', 'system')
ON CONFLICT (user_id, tenant_id) DO NOTHING;
ALTER TABLE nexent.mcp_record_t
ADD COLUMN IF NOT EXISTS container_id VARCHAR(200);

COMMENT ON COLUMN nexent.mcp_record_t.container_id IS 'Docker container ID for MCP service, NULL for non-containerized MCP';


CREATE SEQUENCE IF NOT EXISTS "nexent"."ag_tenant_agent_t_agent_id_seq"
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;-- Delete erroneous tenant with empty tenant_id and all related data
-- This script removes records where tenant_id is empty string from tenant_config_t and tenant_group_info_t

-- 1. Force delete all records in tenant_config_t where tenant_id is empty string
DELETE FROM nexent.tenant_config_t
WHERE tenant_id = '';

-- 2. Force delete all records in tenant_group_info_t where tenant_id is empty string
DELETE FROM nexent.tenant_group_info_t
WHERE tenant_id = '';
-- Migration: Add authorization_token column to mcp_record_t table
-- Date: 2025-03-01
-- Description: Add authorization_token field to support MCP server authentication

-- Add authorization_token column to mcp_record_t table
ALTER TABLE nexent.mcp_record_t
ADD COLUMN IF NOT EXISTS authorization_token VARCHAR(500) DEFAULT NULL;

-- Add comment to the column
COMMENT ON COLUMN nexent.mcp_record_t.authorization_token IS 'Authorization token for MCP server authentication (e.g., Bearer token)';
-- Migration: Add ingroup_permission column to ag_tenant_agent_t table
-- Date: 2025-03-02
-- Description: Add ingroup_permission field to support in-group permission control for agents

-- Add ingroup_permission column to ag_tenant_agent_t table
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS ingroup_permission VARCHAR(30) DEFAULT NULL;

-- Add comment to the column
COMMENT ON COLUMN nexent.ag_tenant_agent_t.ingroup_permission IS 'In-group permission: EDIT, READ_ONLY, PRIVATE';
-- Step 1: Create sequence for auto-increment
CREATE SEQUENCE IF NOT EXISTS "nexent"."ag_tool_instance_t_tool_instance_id_seq"
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

CREATE SEQUENCE IF NOT EXISTS "nexent"."ag_agent_relation_t_relation_id_seq"
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;
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
-- 步骤 1：添加 nullable 的 version_no 字段（不设默认值，让显式赋值）
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS version_no INTEGER NULL;

ALTER TABLE nexent.ag_tool_instance_t
ADD COLUMN IF NOT EXISTS version_no INTEGER NULL;

ALTER TABLE nexent.ag_agent_relation_t
ADD COLUMN IF NOT EXISTS version_no INTEGER NULL;

-- 步骤 2：更新所有历史数据的 version_no 为 0
UPDATE nexent.ag_tenant_agent_t SET version_no = 0 WHERE version_no IS NULL;
UPDATE nexent.ag_tool_instance_t SET version_no = 0 WHERE version_no IS NULL;
UPDATE nexent.ag_agent_relation_t SET version_no = 0 WHERE version_no IS NULL;

-- 步骤 3：将字段设为 NOT NULL，并设置默认值 0
ALTER TABLE nexent.ag_tenant_agent_t ALTER COLUMN version_no SET NOT NULL;
ALTER TABLE nexent.ag_tenant_agent_t ALTER COLUMN version_no SET DEFAULT 0;

ALTER TABLE nexent.ag_tool_instance_t ALTER COLUMN version_no SET NOT NULL;
ALTER TABLE nexent.ag_tool_instance_t ALTER COLUMN version_no SET DEFAULT 0;

ALTER TABLE nexent.ag_agent_relation_t ALTER COLUMN version_no SET NOT NULL;
ALTER TABLE nexent.ag_agent_relation_t ALTER COLUMN version_no SET DEFAULT 0;

-- 步骤 4：为 ag_tenant_agent_t 添加 current_version_no 字段
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS current_version_no INTEGER NULL;

-- 步骤5：修改主键
ALTER TABLE nexent.ag_tenant_agent_t DROP CONSTRAINT ag_tenant_agent_t_pkey;
ALTER TABLE nexent.ag_tenant_agent_t ADD CONSTRAINT ag_tenant_agent_t_pkey PRIMARY KEY (agent_id, version_no);

ALTER TABLE nexent.ag_tool_instance_t DROP CONSTRAINT ag_tool_instance_t_pkey;
ALTER TABLE nexent.ag_tool_instance_t ADD CONSTRAINT ag_tool_instance_t_pkey PRIMARY KEY (tool_instance_id, version_no);

ALTER TABLE nexent.ag_agent_relation_t DROP CONSTRAINT ag_agent_relation_t_pkey;
ALTER TABLE nexent.ag_agent_relation_t ADD CONSTRAINT ag_agent_relation_t_pkey PRIMARY KEY (relation_id, version_no);

-- 步骤6：新增agent版本管理表
CREATE TABLE IF NOT EXISTS nexent.ag_tenant_agent_version_t (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    agent_id INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
    version_name VARCHAR(100),                    -- 用户自定义版本名称
    release_note TEXT,                            -- 发布备注

    source_version_no INTEGER NULL,               -- 来源版本号（回滚时记录）
    source_type VARCHAR(30) NULL,                 -- 来源类型：NORMAL(正常发布) / ROLLBACK(回滚产生)

    status VARCHAR(30) DEFAULT 'RELEASED',        -- 版本状态：RELEASED / DISABLED / ARCHIVED

    created_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_tenant_agent_version_t OWNER TO "root";

-- 步骤 7：添加COMMENT
COMMENT ON COLUMN nexent.ag_tenant_agent_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.current_version_no IS 'Current published version number. NULL means no version published yet';
COMMENT ON COLUMN nexent.ag_tool_instance_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';
COMMENT ON COLUMN nexent.ag_agent_relation_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';

COMMENT ON TABLE nexent.ag_tenant_agent_version_t IS 'Agent version metadata table. Stores version info, release notes, and version lineage.';

COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.id IS 'Primary key, auto-increment';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.agent_id IS 'Agent ID';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.version_no IS 'Version number, starts from 1. Does not include 0 (draft)';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.version_name IS 'User-defined version name for display (e.g., "Stable v2.1", "Hotfix-001"). NULL means use version_no as display.';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.release_note IS 'Release notes / publish remarks';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.source_version_no IS 'Source version number. If this version is a rollback, record the source version number.';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.source_type IS 'Source type: NORMAL (normal publish) / ROLLBACK (rollback and republish).';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.status IS 'Version status: RELEASED / DISABLED / ARCHIVED';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.created_by IS 'User who published this version';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.create_time IS 'Version creation timestamp';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.updated_by IS 'Last user who updated this version';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.update_time IS 'Last update timestamp';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.delete_flag IS 'Soft delete flag: Y/N';
DELETE FROM nexent.role_permission_t;

INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(2, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(3, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/tenant-resources'),
(4, 'SU', 'RESOURCE', 'AGENT', 'READ'),
(5, 'SU', 'RESOURCE', 'AGENT', 'DELETE'),
(6, 'SU', 'RESOURCE', 'KB', 'READ'),
(7, 'SU', 'RESOURCE', 'KB', 'DELETE'),
(8, 'SU', 'RESOURCE', 'KB.GROUPS', 'READ'),
(9, 'SU', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(10, 'SU', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(11, 'SU', 'RESOURCE', 'USER.ROLE', 'READ'),
(12, 'SU', 'RESOURCE', 'USER.ROLE', 'UPDATE'),
(13, 'SU', 'RESOURCE', 'USER.ROLE', 'DELETE'),
(14, 'SU', 'RESOURCE', 'MCP', 'READ'),
(15, 'SU', 'RESOURCE', 'MCP', 'DELETE'),
(16, 'SU', 'RESOURCE', 'MEM.SETTING', 'READ'),
(17, 'SU', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(18, 'SU', 'RESOURCE', 'MEM.AGENT', 'READ'),
(19, 'SU', 'RESOURCE', 'MEM.AGENT', 'DELETE'),
(20, 'SU', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(21, 'SU', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(22, 'SU', 'RESOURCE', 'MODEL', 'CREATE'),
(23, 'SU', 'RESOURCE', 'MODEL', 'READ'),
(24, 'SU', 'RESOURCE', 'MODEL', 'UPDATE'),
(25, 'SU', 'RESOURCE', 'MODEL', 'DELETE'),
(26, 'SU', 'RESOURCE', 'TENANT', 'CREATE'),
(27, 'SU', 'RESOURCE', 'TENANT', 'READ'),
(28, 'SU', 'RESOURCE', 'TENANT', 'UPDATE'),
(29, 'SU', 'RESOURCE', 'TENANT', 'DELETE'),
(30, 'SU', 'RESOURCE', 'TENANT.LIST', 'READ'),
(31, 'SU', 'RESOURCE', 'TENANT.INFO', 'READ'),
(32, 'SU', 'RESOURCE', 'TENANT.INFO', 'UPDATE'),
(33, 'SU', 'RESOURCE', 'TENANT.INVITE', 'CREATE'),
(34, 'SU', 'RESOURCE', 'TENANT.INVITE', 'READ'),
(35, 'SU', 'RESOURCE', 'TENANT.INVITE', 'UPDATE'),
(36, 'SU', 'RESOURCE', 'TENANT.INVITE', 'DELETE'),
(37, 'SU', 'RESOURCE', 'GROUP', 'CREATE'),
(38, 'SU', 'RESOURCE', 'GROUP', 'READ'),
(39, 'SU', 'RESOURCE', 'GROUP', 'UPDATE'),
(40, 'SU', 'RESOURCE', 'GROUP', 'DELETE'),
(41, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(42, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(43, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/setup'),
(44, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(45, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/market'),
(46, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents'),
(47, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(48, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(49, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(50, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(51, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(52, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(53, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/tenant-resources'),
(54, 'ADMIN', 'RESOURCE', 'AGENT', 'CREATE'),
(55, 'ADMIN', 'RESOURCE', 'AGENT', 'READ'),
(56, 'ADMIN', 'RESOURCE', 'AGENT', 'UPDATE'),
(57, 'ADMIN', 'RESOURCE', 'AGENT', 'DELETE'),
(58, 'ADMIN', 'RESOURCE', 'KB', 'CREATE'),
(59, 'ADMIN', 'RESOURCE', 'KB', 'READ'),
(60, 'ADMIN', 'RESOURCE', 'KB', 'UPDATE'),
(61, 'ADMIN', 'RESOURCE', 'KB', 'DELETE'),
(62, 'ADMIN', 'RESOURCE', 'KB.GROUPS', 'READ'),
(63, 'ADMIN', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(64, 'ADMIN', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(65, 'ADMIN', 'RESOURCE', 'USER.ROLE', 'READ'),
(66, 'ADMIN', 'RESOURCE', 'MCP', 'CREATE'),
(67, 'ADMIN', 'RESOURCE', 'MCP', 'READ'),
(68, 'ADMIN', 'RESOURCE', 'MCP', 'UPDATE'),
(69, 'ADMIN', 'RESOURCE', 'MCP', 'DELETE'),
(70, 'ADMIN', 'RESOURCE', 'MEM.SETTING', 'READ'),
(71, 'ADMIN', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(72, 'ADMIN', 'RESOURCE', 'MEM.AGENT', 'CREATE'),
(73, 'ADMIN', 'RESOURCE', 'MEM.AGENT', 'READ'),
(74, 'ADMIN', 'RESOURCE', 'MEM.AGENT', 'DELETE'),
(75, 'ADMIN', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(76, 'ADMIN', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(77, 'ADMIN', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(78, 'ADMIN', 'RESOURCE', 'MODEL', 'CREATE'),
(79, 'ADMIN', 'RESOURCE', 'MODEL', 'READ'),
(80, 'ADMIN', 'RESOURCE', 'MODEL', 'UPDATE'),
(81, 'ADMIN', 'RESOURCE', 'MODEL', 'DELETE'),
(82, 'ADMIN', 'RESOURCE', 'TENANT.INFO', 'READ'),
(83, 'ADMIN', 'RESOURCE', 'TENANT.INFO', 'UPDATE'),
(84, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'CREATE'),
(85, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'READ'),
(86, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'UPDATE'),
(87, 'ADMIN', 'RESOURCE', 'TENANT.INVITE', 'DELETE'),
(88, 'ADMIN', 'RESOURCE', 'GROUP', 'CREATE'),
(89, 'ADMIN', 'RESOURCE', 'GROUP', 'READ'),
(90, 'ADMIN', 'RESOURCE', 'GROUP', 'UPDATE'),
(91, 'ADMIN', 'RESOURCE', 'GROUP', 'DELETE'),
(92, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(93, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(94, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/setup'),
(95, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(96, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/market'),
(97, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents'),
(98, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(99, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(100, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(101, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(102, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(103, 'DEV', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(104, 'DEV', 'RESOURCE', 'AGENT', 'CREATE'),
(105, 'DEV', 'RESOURCE', 'AGENT', 'READ'),
(106, 'DEV', 'RESOURCE', 'AGENT', 'UPDATE'),
(107, 'DEV', 'RESOURCE', 'AGENT', 'DELETE'),
(108, 'DEV', 'RESOURCE', 'KB', 'CREATE'),
(109, 'DEV', 'RESOURCE', 'KB', 'READ'),
(110, 'DEV', 'RESOURCE', 'KB', 'UPDATE'),
(111, 'DEV', 'RESOURCE', 'KB', 'DELETE'),
(112, 'DEV', 'RESOURCE', 'KB.GROUPS', 'READ'),
(113, 'DEV', 'RESOURCE', 'KB.GROUPS', 'UPDATE'),
(114, 'DEV', 'RESOURCE', 'KB.GROUPS', 'DELETE'),
(115, 'DEV', 'RESOURCE', 'USER.ROLE', 'READ'),
(116, 'DEV', 'RESOURCE', 'MCP', 'CREATE'),
(117, 'DEV', 'RESOURCE', 'MCP', 'READ'),
(118, 'DEV', 'RESOURCE', 'MCP', 'UPDATE'),
(119, 'DEV', 'RESOURCE', 'MCP', 'DELETE'),
(120, 'DEV', 'RESOURCE', 'MEM.SETTING', 'READ'),
(121, 'DEV', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(122, 'DEV', 'RESOURCE', 'MEM.AGENT', 'READ'),
(123, 'DEV', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(124, 'DEV', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(125, 'DEV', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(126, 'DEV', 'RESOURCE', 'MODEL', 'READ'),
(127, 'DEV', 'RESOURCE', 'TENANT.INFO', 'READ'),
(128, 'DEV', 'RESOURCE', 'GROUP', 'READ'),
(129, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(130, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(131, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(132, 'USER', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(133, 'USER', 'RESOURCE', 'AGENT', 'READ'),
(134, 'USER', 'RESOURCE', 'USER.ROLE', 'READ'),
(135, 'USER', 'RESOURCE', 'MEM.SETTING', 'READ'),
(136, 'USER', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(137, 'USER', 'RESOURCE', 'MEM.AGENT', 'READ'),
(138, 'USER', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(139, 'USER', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(140, 'USER', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(141, 'USER', 'RESOURCE', 'TENANT.INFO', 'READ'),
(142, 'USER', 'RESOURCE', 'GROUP', 'READ'),
(143, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(144, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/chat'),
(145, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/setup'),
(146, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(147, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/market'),
(148, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/agents'),
(149, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(150, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(151, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(152, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(153, 'SPEED', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(154, 'SPEED', 'RESOURCE', 'AGENT', 'CREATE'),
(155, 'SPEED', 'RESOURCE', 'AGENT', 'READ'),
(156, 'SPEED', 'RESOURCE', 'AGENT', 'UPDATE'),
(157, 'SPEED', 'RESOURCE', 'AGENT', 'DELETE'),
(158, 'SPEED', 'RESOURCE', 'KB', 'CREATE'),
(159, 'SPEED', 'RESOURCE', 'KB', 'READ'),
(160, 'SPEED', 'RESOURCE', 'KB', 'UPDATE'),
(161, 'SPEED', 'RESOURCE', 'KB', 'DELETE'),
(166, 'SPEED', 'RESOURCE', 'MCP', 'CREATE'),
(167, 'SPEED', 'RESOURCE', 'MCP', 'READ'),
(168, 'SPEED', 'RESOURCE', 'MCP', 'UPDATE'),
(169, 'SPEED', 'RESOURCE', 'MCP', 'DELETE'),
(170, 'SPEED', 'RESOURCE', 'MEM.SETTING', 'READ'),
(171, 'SPEED', 'RESOURCE', 'MEM.SETTING', 'UPDATE'),
(172, 'SPEED', 'RESOURCE', 'MEM.AGENT', 'CREATE'),
(173, 'SPEED', 'RESOURCE', 'MEM.AGENT', 'READ'),
(174, 'SPEED', 'RESOURCE', 'MEM.AGENT', 'DELETE'),
(175, 'SPEED', 'RESOURCE', 'MEM.PRIVATE', 'CREATE'),
(176, 'SPEED', 'RESOURCE', 'MEM.PRIVATE', 'READ'),
(177, 'SPEED', 'RESOURCE', 'MEM.PRIVATE', 'DELETE'),
(178, 'SPEED', 'RESOURCE', 'MODEL', 'CREATE'),
(179, 'SPEED', 'RESOURCE', 'MODEL', 'READ'),
(180, 'SPEED', 'RESOURCE', 'MODEL', 'UPDATE'),
(181, 'SPEED', 'RESOURCE', 'MODEL', 'DELETE'),
(182, 'SPEED', 'RESOURCE', 'TENANT.INFO', 'READ'),
(183, 'SPEED', 'RESOURCE', 'TENANT.INFO', 'UPDATE'),
(184, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'CREATE'),
(185, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'READ'),
(186, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'UPDATE'),
(187, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'DELETE')
