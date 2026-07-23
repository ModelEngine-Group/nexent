-- 1. Create custom Schema (if not exists)
CREATE SCHEMA IF NOT EXISTS nexent;

-- 2. Switch to the Schema (subsequent operations default to this Schema)
SET search_path TO nexent;

CREATE TABLE IF NOT EXISTS "conversation_message_t" (
  "message_id" SERIAL,
  "conversation_id" int4,
  "message_index" int4,
  "message_role" varchar(30) COLLATE "pg_catalog"."default",
  "message_content" varchar COLLATE "pg_catalog"."default",
  "minio_files" varchar,
  "opinion_flag" varchar(1),
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'::character varying,
  "create_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "update_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "created_by" varchar(100) COLLATE "pg_catalog"."default",
  "updated_by" varchar(100) COLLATE "pg_catalog"."default",
  CONSTRAINT "conversation_message_t_pk" PRIMARY KEY ("message_id")
);
ALTER TABLE "conversation_message_t" OWNER TO "root";
COMMENT ON COLUMN "conversation_message_t"."conversation_id" IS 'Formal foreign key, used to associate with the conversation';
COMMENT ON COLUMN "conversation_message_t"."message_index" IS 'Sequence number, used for frontend display sorting';
COMMENT ON COLUMN "conversation_message_t"."message_role" IS 'Role sending the message, such as system, assistant, user';
COMMENT ON COLUMN "conversation_message_t"."message_content" IS 'Complete content of the message';
COMMENT ON COLUMN "conversation_message_t"."minio_files" IS 'Images or documents uploaded by users in the chat interface, stored as a list';
COMMENT ON COLUMN "conversation_message_t"."opinion_flag" IS 'User feedback on the conversation, enum value Y represents positive, N represents negative';
COMMENT ON COLUMN "conversation_message_t"."delete_flag" IS 'When deleted by user frontend, delete flag will be set to true, achieving soft delete effect. Optional values Y/N';
COMMENT ON COLUMN "conversation_message_t"."create_time" IS 'Creation time, audit field';
COMMENT ON COLUMN "conversation_message_t"."update_time" IS 'Update time, audit field';
COMMENT ON COLUMN "conversation_message_t"."created_by" IS 'Creator ID, audit field';
COMMENT ON COLUMN "conversation_message_t"."updated_by" IS 'Last updater ID, audit field';
COMMENT ON TABLE "conversation_message_t" IS 'Carries specific response message content in conversations';

CREATE TABLE IF NOT EXISTS "conversation_message_unit_t" (
  "unit_id" SERIAL,
  "message_id" int4,
  "conversation_id" int4,
  "unit_index" int4,
  "unit_type" varchar(100) COLLATE "pg_catalog"."default",
  "unit_content" varchar COLLATE "pg_catalog"."default",
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'::character varying,
  "create_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "update_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "updated_by" varchar(100) COLLATE "pg_catalog"."default",
  "created_by" varchar(100) COLLATE "pg_catalog"."default",
  "step_index" int4,
  CONSTRAINT "conversation_message_unit_t_pk" PRIMARY KEY ("unit_id")
);
ALTER TABLE "conversation_message_unit_t" OWNER TO "root";
COMMENT ON COLUMN "conversation_message_unit_t"."message_id" IS 'Formal foreign key, used to associate with the message';
COMMENT ON COLUMN "conversation_message_unit_t"."conversation_id" IS 'Formal foreign key, used to associate with the conversation';
COMMENT ON COLUMN "conversation_message_unit_t"."unit_index" IS 'Sequence number, used for frontend display sorting';
COMMENT ON COLUMN "conversation_message_unit_t"."unit_type" IS 'Type of minimum response unit';
COMMENT ON COLUMN "conversation_message_unit_t"."unit_content" IS 'Complete content of the minimum response unit';
COMMENT ON COLUMN "conversation_message_unit_t"."delete_flag" IS 'When deleted by user frontend, delete flag will be set to true, achieving soft delete effect. Optional values Y/N';
COMMENT ON COLUMN "conversation_message_unit_t"."create_time" IS 'Creation time, audit field';
COMMENT ON COLUMN "conversation_message_unit_t"."update_time" IS 'Update time, audit field';
COMMENT ON COLUMN "conversation_message_unit_t"."updated_by" IS 'Last updater ID, audit field';
COMMENT ON COLUMN "conversation_message_unit_t"."created_by" IS 'Creator ID, audit field';
COMMENT ON COLUMN "conversation_message_unit_t"."step_index" IS 'ReAct step sequence number within this message. Increments on step_count chunks';
COMMENT ON TABLE "conversation_message_unit_t" IS 'Carries agent output content in each message';

CREATE TABLE IF NOT EXISTS "conversation_record_t" (
  "conversation_id" SERIAL,
  "conversation_title" varchar(100) COLLATE "pg_catalog"."default",
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'::character varying,
  "update_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "create_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "updated_by" varchar(100) COLLATE "pg_catalog"."default",
  "created_by" varchar(100) COLLATE "pg_catalog"."default",
  CONSTRAINT "conversation_record_t_pk" PRIMARY KEY ("conversation_id")
);
ALTER TABLE "conversation_record_t" OWNER TO "root";
COMMENT ON COLUMN "conversation_record_t"."conversation_title" IS 'Conversation title';
COMMENT ON COLUMN "conversation_record_t"."delete_flag" IS 'When deleted by user frontend, delete flag will be set to true, achieving soft delete effect. Optional values Y/N';
COMMENT ON COLUMN "conversation_record_t"."update_time" IS 'Update time, audit field';
COMMENT ON COLUMN "conversation_record_t"."create_time" IS 'Creation time, audit field';
COMMENT ON COLUMN "conversation_record_t"."updated_by" IS 'Last updater ID, audit field';
COMMENT ON COLUMN "conversation_record_t"."created_by" IS 'Creator ID, audit field';
COMMENT ON TABLE "conversation_record_t" IS 'Overall information of Q&A conversations';

CREATE TABLE IF NOT EXISTS "conversation_source_image_t" (
  "image_id" SERIAL,
  "conversation_id" int4,
  "message_id" int4,
  "unit_id" int4,
  "image_url" varchar COLLATE "pg_catalog"."default",
  "cite_index" int4,
  "search_type" varchar(100) COLLATE "pg_catalog"."default",
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'::character varying,
  "create_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "update_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "created_by" varchar(100) COLLATE "pg_catalog"."default",
  "updated_by" varchar(100) COLLATE "pg_catalog"."default",
  CONSTRAINT "conversation_source_image_t_pk" PRIMARY KEY ("image_id")
);
ALTER TABLE "conversation_source_image_t" OWNER TO "root";
COMMENT ON COLUMN "conversation_source_image_t"."conversation_id" IS 'Formal foreign key, used to associate with the conversation of the search source';
COMMENT ON COLUMN "conversation_source_image_t"."message_id" IS 'Formal foreign key, used to associate with the conversation message of the search source';
COMMENT ON COLUMN "conversation_source_image_t"."unit_id" IS 'Formal foreign key, used to associate with the minimum message unit of the search source (if any)';
COMMENT ON COLUMN "conversation_source_image_t"."image_url" IS 'URL address of the image';
COMMENT ON COLUMN "conversation_source_image_t"."cite_index" IS '[Reserved] Citation sequence number, used for precise tracing';
COMMENT ON COLUMN "conversation_source_image_t"."search_type" IS '[Reserved] Search source type, used to distinguish the search tool used for this record, optional values web/local';
COMMENT ON COLUMN "conversation_source_image_t"."delete_flag" IS 'When deleted by user frontend, delete flag will be set to true, achieving soft delete effect. Optional values Y/N';
COMMENT ON COLUMN "conversation_source_image_t"."create_time" IS 'Creation time, audit field';
COMMENT ON COLUMN "conversation_source_image_t"."update_time" IS 'Update time, audit field';
COMMENT ON COLUMN "conversation_source_image_t"."created_by" IS 'Creator ID, audit field';
COMMENT ON COLUMN "conversation_source_image_t"."updated_by" IS 'Last updater ID, audit field';
COMMENT ON TABLE "conversation_source_image_t" IS 'Carries search image source information for conversation messages';

CREATE TABLE IF NOT EXISTS "conversation_source_search_t" (
  "search_id" SERIAL,
  "unit_id" int4,
  "message_id" int4,
  "conversation_id" int4,
  "source_type" varchar(100) COLLATE "pg_catalog"."default",
  "source_title" varchar(400) COLLATE "pg_catalog"."default",
  "source_location" varchar(400) COLLATE "pg_catalog"."default",
  "source_content" varchar COLLATE "pg_catalog"."default",
  "score_overall" numeric(7,6),
  "score_accuracy" numeric(7,6),
  "score_semantic" numeric(7,6),
  "published_date" timestamp(0),
  "cite_index" int4,
  "search_type" varchar(100) COLLATE "pg_catalog"."default",
  "tool_sign" varchar(30) COLLATE "pg_catalog"."default",
  "create_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "update_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'::character varying,
  "updated_by" varchar(100) COLLATE "pg_catalog"."default",
  "created_by" varchar(100) COLLATE "pg_catalog"."default",
  CONSTRAINT "conversation_source_search_t_pk" PRIMARY KEY ("search_id")
);
ALTER TABLE "conversation_source_search_t" OWNER TO "root";
COMMENT ON COLUMN "conversation_source_search_t"."unit_id" IS 'Formal foreign key, used to associate with the minimum message unit of the search source (if any)';
COMMENT ON COLUMN "conversation_source_search_t"."message_id" IS 'Formal foreign key, used to associate with the conversation message of the search source';
COMMENT ON COLUMN "conversation_source_search_t"."conversation_id" IS 'Formal foreign key, used to associate with the conversation of the search source';
COMMENT ON COLUMN "conversation_source_search_t"."source_type" IS 'Source type, used to distinguish if source_location is URL or path, optional values url/text';
COMMENT ON COLUMN "conversation_source_search_t"."source_title" IS 'Title or filename of the search source';
COMMENT ON COLUMN "conversation_source_search_t"."source_location" IS 'URL link or file path of the search source';
COMMENT ON COLUMN "conversation_source_search_t"."source_content" IS 'Original text of the search source';
COMMENT ON COLUMN "conversation_source_search_t"."score_overall" IS 'Overall similarity score between source and user query, calculated as weighted average of details';
COMMENT ON COLUMN "conversation_source_search_t"."score_accuracy" IS 'Accuracy score';
COMMENT ON COLUMN "conversation_source_search_t"."score_semantic" IS 'Semantic similarity score';
COMMENT ON COLUMN "conversation_source_search_t"."published_date" IS 'Upload date of local file or network search date';
COMMENT ON COLUMN "conversation_source_search_t"."cite_index" IS 'Citation sequence number, used for precise tracing';
COMMENT ON COLUMN "conversation_source_search_t"."search_type" IS 'Search source type, specifically describes the search tool used for this record, optional values web_search/knowledge_base_search';
COMMENT ON COLUMN "conversation_source_search_t"."tool_sign" IS 'Simple tool identifier, used to distinguish index sources in large model output summary text';
COMMENT ON COLUMN "conversation_source_search_t"."create_time" IS 'Creation time, audit field';
COMMENT ON COLUMN "conversation_source_search_t"."update_time" IS 'Update time, audit field';
COMMENT ON COLUMN "conversation_source_search_t"."delete_flag" IS 'When deleted by user frontend, delete flag will be set to true, achieving soft delete effect. Optional values Y/N';
COMMENT ON COLUMN "conversation_source_search_t"."updated_by" IS 'Last updater ID, audit field';
COMMENT ON COLUMN "conversation_source_search_t"."created_by" IS 'Creator ID, audit field';
COMMENT ON TABLE "conversation_source_search_t" IS 'Carries search text source information referenced in conversation response messages';

CREATE TABLE IF NOT EXISTS "model_record_t" (
  "model_id" SERIAL,
  "model_repo" varchar(100) COLLATE "pg_catalog"."default",
  "model_name" varchar(100) COLLATE "pg_catalog"."default" NOT NULL,
  "model_factory" varchar(100) COLLATE "pg_catalog"."default",
  "model_type" varchar(100) COLLATE "pg_catalog"."default",
  "api_key" varchar(500) COLLATE "pg_catalog"."default",
  "base_url" varchar(500) COLLATE "pg_catalog"."default",
  "max_tokens" int4,
  "used_token" int4,
  "display_name" varchar(100) COLLATE "pg_catalog"."default",
  "connect_status" varchar(100) COLLATE "pg_catalog"."default",
  "create_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'::character varying,
  "update_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "updated_by" varchar(100) COLLATE "pg_catalog"."default",
  "created_by" varchar(100) COLLATE "pg_catalog"."default",
  CONSTRAINT "nexent_models_t_pk" PRIMARY KEY ("model_id")
);
ALTER TABLE "model_record_t" OWNER TO "root";
COMMENT ON COLUMN "model_record_t"."model_id" IS 'Model ID, unique primary key';
COMMENT ON COLUMN "model_record_t"."model_repo" IS 'Model path address';
COMMENT ON COLUMN "model_record_t"."model_name" IS 'Model name';
COMMENT ON COLUMN "model_record_t"."model_factory" IS 'Model manufacturer, determines specific format of api-key and model response. Currently defaults to OpenAI-API-Compatible';
COMMENT ON COLUMN "model_record_t"."model_type" IS 'Model type, e.g. chat, embedding, rerank, tts, asr';
COMMENT ON COLUMN "model_record_t"."api_key" IS 'Model API key, used for authentication for some models';
COMMENT ON COLUMN "model_record_t"."base_url" IS 'Base URL address, used for requesting remote model services';
COMMENT ON COLUMN "model_record_t"."max_tokens" IS 'Maximum available tokens for the model';
COMMENT ON COLUMN "model_record_t"."used_token" IS 'Number of tokens already used by the model in Q&A';
COMMENT ON COLUMN "model_record_t"."display_name" IS 'Model name displayed directly in frontend, customized by user';
COMMENT ON COLUMN "model_record_t"."connect_status" IS 'Model connectivity status from last check, optional values: "检测中"、"可用"、"不可用"';
COMMENT ON COLUMN "model_record_t"."create_time" IS 'Creation time, audit field';
COMMENT ON COLUMN "model_record_t"."delete_flag" IS 'When deleted by user frontend, delete flag will be set to true, achieving soft delete effect. Optional values Y/N';
COMMENT ON COLUMN "model_record_t"."update_time" IS 'Update time, audit field';
COMMENT ON COLUMN "model_record_t"."updated_by" IS 'Last updater ID, audit field';
COMMENT ON COLUMN "model_record_t"."created_by" IS 'Creator ID, audit field';
COMMENT ON TABLE "model_record_t" IS 'List of models defined by users in the configuration page';

INSERT INTO "nexent"."model_record_t" ("model_repo", "model_name", "model_factory", "model_type", "api_key", "base_url", "max_tokens", "used_token", "display_name", "connect_status")
SELECT '', 'volcano_tts', 'OpenAI-API-Compatible', 'tts', '', '', 0, 0, 'volcano_tts', 'unavailable'
WHERE NOT EXISTS (
  SELECT 1 FROM "nexent"."model_record_t"
  WHERE "model_name" = 'volcano_tts' AND "model_type" = 'tts'
);
INSERT INTO "nexent"."model_record_t" ("model_repo", "model_name", "model_factory", "model_type", "api_key", "base_url", "max_tokens", "used_token", "display_name", "connect_status")
SELECT '', 'volcano_stt', 'OpenAI-API-Compatible', 'stt', '', '', 0, 0, 'volcano_stt', 'unavailable'
WHERE NOT EXISTS (
  SELECT 1 FROM "nexent"."model_record_t"
  WHERE "model_name" = 'volcano_stt' AND "model_type" = 'stt'
);

CREATE TABLE IF NOT EXISTS "knowledge_record_t" (
  "knowledge_id" SERIAL,
  "index_name" varchar(100) COLLATE "pg_catalog"."default",
  "knowledge_describe" varchar(300) COLLATE "pg_catalog"."default",
  "tenant_id" varchar(100) COLLATE "pg_catalog"."default",
  "create_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "update_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'::character varying,
  "updated_by" varchar(100) COLLATE "pg_catalog"."default",
  "created_by" varchar(100) COLLATE "pg_catalog"."default",
  CONSTRAINT "knowledge_record_t_pk" PRIMARY KEY ("knowledge_id")
);
ALTER TABLE "knowledge_record_t" OWNER TO "root";
COMMENT ON COLUMN "knowledge_record_t"."knowledge_id" IS 'Knowledge base ID, unique primary key';
COMMENT ON COLUMN "knowledge_record_t"."index_name" IS 'Knowledge base name';
COMMENT ON COLUMN "knowledge_record_t"."knowledge_describe" IS 'Knowledge base description';
COMMENT ON COLUMN "knowledge_record_t"."tenant_id" IS 'Tenant ID';
COMMENT ON COLUMN "knowledge_record_t"."create_time" IS 'Creation time, audit field';
COMMENT ON COLUMN "knowledge_record_t"."update_time" IS 'Update time, audit field';
COMMENT ON COLUMN "knowledge_record_t"."delete_flag" IS 'When deleted by user frontend, delete flag will be set to true, achieving soft delete effect. Optional values Y/N';
COMMENT ON COLUMN "knowledge_record_t"."updated_by" IS 'Last updater ID, audit field';
COMMENT ON COLUMN "knowledge_record_t"."created_by" IS 'Creator ID, audit field';
COMMENT ON TABLE "knowledge_record_t" IS 'Records knowledge base description and status information';

-- Create the ag_tool_info_t table
CREATE TABLE IF NOT EXISTS nexent.ag_tool_info_t (
    tool_id SERIAL PRIMARY KEY NOT NULL,
    name VARCHAR(100),
    class_name VARCHAR(100),
    description VARCHAR,
    source VARCHAR(100),
    author VARCHAR(100),
    usage VARCHAR(100),
    params JSON,
    inputs VARCHAR,
    output_type VARCHAR(100),
    is_available BOOLEAN DEFAULT FALSE,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Trigger to update update_time when the record is modified
CREATE OR REPLACE FUNCTION update_ag_tool_info_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_ag_tool_info_update_time_trigger ON nexent.ag_tool_info_t;
CREATE TRIGGER update_ag_tool_info_update_time_trigger
BEFORE UPDATE ON nexent.ag_tool_info_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_tool_info_update_time();

-- Add comment to the table
COMMENT ON TABLE nexent.ag_tool_info_t IS 'Information table for prompt tools';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_tool_info_t.tool_id IS 'ID';
COMMENT ON COLUMN nexent.ag_tool_info_t.name IS 'Unique key name';
COMMENT ON COLUMN nexent.ag_tool_info_t.class_name IS 'Tool class name, used when the tool is instantiated';
COMMENT ON COLUMN nexent.ag_tool_info_t.description IS 'Prompt tool description';
COMMENT ON COLUMN nexent.ag_tool_info_t.source IS 'Source';
COMMENT ON COLUMN nexent.ag_tool_info_t.author IS 'Tool author';
COMMENT ON COLUMN nexent.ag_tool_info_t.usage IS 'Usage';
COMMENT ON COLUMN nexent.ag_tool_info_t.params IS 'Tool parameter information (json)';
COMMENT ON COLUMN nexent.ag_tool_info_t.inputs IS 'Prompt tool inputs description';
COMMENT ON COLUMN nexent.ag_tool_info_t.output_type IS 'Prompt tool output description';
COMMENT ON COLUMN nexent.ag_tool_info_t.is_available IS 'Whether the tool can be used under the current main service';
COMMENT ON COLUMN nexent.ag_tool_info_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_tool_info_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_tool_info_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.ag_tool_info_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.ag_tool_info_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create the ag_tenant_agent_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.ag_tenant_agent_t (
    agent_id SERIAL PRIMARY KEY NOT NULL,
    name VARCHAR(100),
    description VARCHAR,
    business_description VARCHAR,
    model_name VARCHAR(100),
    max_steps INTEGER,
    prompt TEXT,
    parent_agent_id INTEGER,
    tenant_id VARCHAR(100),
    enabled BOOLEAN DEFAULT FALSE,
    is_main_agent BOOLEAN NOT NULL DEFAULT TRUE,
    provide_run_summary BOOLEAN DEFAULT FALSE,
    context_policy JSONB,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_ag_tenant_agent_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create a trigger to call the function before each update
DROP TRIGGER IF EXISTS update_ag_tenant_agent_update_time_trigger ON nexent.ag_tenant_agent_t;
CREATE TRIGGER update_ag_tenant_agent_update_time_trigger
BEFORE UPDATE ON nexent.ag_tenant_agent_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_tenant_agent_update_time();
-- Add comments to the table
COMMENT ON TABLE nexent.ag_tenant_agent_t IS 'Information table for agents';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_tenant_agent_t.agent_id IS 'ID';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.name IS 'Agent name';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.description IS 'Description';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.business_description IS 'Manually entered by the user to describe the entire business process';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.model_name IS 'Name of the model used';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.max_steps IS 'Maximum number of steps';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.parent_agent_id IS 'Parent Agent ID';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.tenant_id IS 'Belonging tenant';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.enabled IS 'Enable flag';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.is_main_agent IS 'Whether this agent is a main agent';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.provide_run_summary IS 'Whether to provide the running summary to the manager agent';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create the ag_user_agent_t table in the nexent schema with new fields
CREATE TABLE IF NOT EXISTS nexent.ag_user_agent_t (
    user_agent_id SERIAL PRIMARY KEY NOT NULL,
    agent_id INTEGER,
    prompt TEXT,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    enabled BOOLEAN DEFAULT FALSE,
    provide_run_summary BOOLEAN DEFAULT FALSE,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Add comment to the table
COMMENT ON TABLE nexent.ag_user_agent_t IS 'Information table for user agents';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_user_agent_t.user_agent_id IS 'ID';
COMMENT ON COLUMN nexent.ag_user_agent_t.agent_id IS 'Agent ID';
COMMENT ON COLUMN nexent.ag_user_agent_t.prompt IS 'System prompt';
COMMENT ON COLUMN nexent.ag_user_agent_t.tenant_id IS 'Belonging tenant';
COMMENT ON COLUMN nexent.ag_user_agent_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.ag_user_agent_t.enabled IS 'Enable flag';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.provide_run_summary IS 'Whether to provide the running summary to the manager agent';
COMMENT ON COLUMN nexent.ag_user_agent_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_user_agent_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_user_agent_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_ag_user_agent_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add comment to the function
COMMENT ON FUNCTION update_ag_user_agent_update_time() IS 'Function to update the update_time column when a record in ag_user_agent_t is updated';

-- Create a trigger to call the function before each update
DROP TRIGGER IF EXISTS update_ag_user_agent_update_time_trigger ON nexent.ag_user_agent_t;
CREATE TRIGGER update_ag_user_agent_update_time_trigger
BEFORE UPDATE ON nexent.ag_user_agent_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_user_agent_update_time();

-- Add comment to the trigger
COMMENT ON TRIGGER update_ag_user_agent_update_time_trigger ON nexent.ag_user_agent_t IS 'Trigger to call update_ag_user_agent_update_time function before each update on ag_user_agent_t table';

-- Agent automation tasks, proposals, and run history.
CREATE TABLE IF NOT EXISTS nexent.agent_automation_task_t (
    task_id BIGSERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    conversation_id BIGINT NOT NULL,
    agent_id BIGINT NOT NULL,
    agent_version_no INTEGER,
    title VARCHAR(255) NOT NULL,
    instruction TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    source VARCHAR(32) NOT NULL,
    schedule_mode VARCHAR(16) NOT NULL,
    schedule_rule_type VARCHAR(16) NOT NULL,
    schedule_expr TEXT,
    schedule_config JSONB NOT NULL,
    capability_requirements JSONB,
    capability_bindings JSONB,
    runtime_snapshot JSONB,
    timezone VARCHAR(64) NOT NULL,
    next_fire_at TIMESTAMPTZ,
    last_fire_at TIMESTAMPTZ,
    fire_count INTEGER NOT NULL DEFAULT 0,
    last_run_status VARCHAR(32),
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    timeout_seconds INTEGER NOT NULL,
    overlap_policy VARCHAR(16) NOT NULL,
    misfire_policy VARCHAR(16) NOT NULL,
    lock_owner VARCHAR(128),
    lock_until TIMESTAMPTZ,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE IF NOT EXISTS nexent.agent_automation_run_t (
    run_id BIGSERIAL PRIMARY KEY NOT NULL,
    task_id BIGINT NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    conversation_id BIGINT NOT NULL,
    scheduled_fire_at TIMESTAMPTZ NOT NULL,
    actual_fire_at TIMESTAMPTZ,
    trigger_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    generated_prompt TEXT,
    user_message_id BIGINT,
    assistant_message_id BIGINT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    duration_ms BIGINT,
    error_code VARCHAR(64),
    error_message TEXT,
    capability_check JSONB,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE IF NOT EXISTS nexent.agent_automation_proposal_t (
    proposal_id BIGSERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    conversation_id BIGINT NOT NULL,
    agent_id BIGINT NOT NULL,
    proposed_task JSONB NOT NULL,
    capability_resolution JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS idx_agent_automation_due
    ON nexent.agent_automation_task_t (status, next_fire_at)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_agent_automation_owner
    ON nexent.agent_automation_task_t (tenant_id, user_id, status)
    WHERE delete_flag = 'N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_automation_conversation_active
    ON nexent.agent_automation_task_t (conversation_id)
    WHERE delete_flag = 'N' AND status <> 'DELETED';

CREATE INDEX IF NOT EXISTS idx_agent_automation_run_task
    ON nexent.agent_automation_run_t (task_id, scheduled_fire_at)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_agent_automation_run_conversation
    ON nexent.agent_automation_run_t (conversation_id, status)
    WHERE delete_flag = 'N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_automation_active_occurrence
    ON nexent.agent_automation_run_t (task_id, scheduled_fire_at)
    WHERE delete_flag = 'N'
      AND trigger_type = 'SCHEDULED'
      AND status IN ('QUEUED', 'RUNNING');

CREATE INDEX IF NOT EXISTS idx_agent_automation_proposal_owner
    ON nexent.agent_automation_proposal_t (tenant_id, user_id, status)
    WHERE delete_flag = 'N';

-- Create the ag_tool_instance_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.ag_tool_instance_t (
    tool_instance_id SERIAL PRIMARY KEY NOT NULL,
    tool_id INTEGER,
    agent_id INTEGER,
    params JSON,
    user_id VARCHAR(100),
    tenant_id VARCHAR(100),
    enabled BOOLEAN DEFAULT FALSE,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Add comment to the table
COMMENT ON TABLE nexent.ag_tool_instance_t IS 'Information table for tenant tool configuration.';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_tool_instance_t.tool_instance_id IS 'ID';
COMMENT ON COLUMN nexent.ag_tool_instance_t.tool_id IS 'Tenant tool ID';
COMMENT ON COLUMN nexent.ag_tool_instance_t.agent_id IS 'Agent ID';
COMMENT ON COLUMN nexent.ag_tool_instance_t.params IS 'Parameter configuration';
COMMENT ON COLUMN nexent.ag_tool_instance_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.ag_tool_instance_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.ag_tool_instance_t.enabled IS 'Enable flag';
COMMENT ON COLUMN nexent.ag_tool_instance_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_tool_instance_t.update_time IS 'Update time';

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_ag_tool_instance_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add comment to the function
COMMENT ON FUNCTION update_ag_tool_instance_update_time() IS 'Function to update the update_time column when a record in ag_tool_instance_t is updated';

-- Create a trigger to call the function before each update
DROP TRIGGER IF EXISTS update_ag_tool_instance_update_time_trigger ON nexent.ag_tool_instance_t;
CREATE TRIGGER update_ag_tool_instance_update_time_trigger
BEFORE UPDATE ON nexent.ag_tool_instance_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_tool_instance_update_time();

-- Add comment to the trigger
COMMENT ON TRIGGER update_ag_tool_instance_update_time_trigger ON nexent.ag_tool_instance_t IS 'Trigger to call update_ag_tool_instance_update_time function before each update on ag_tool_instance_t table';

-- ============================================================================
-- Phase 2 Memory Architecture: memory_records_t / memory_retrieval_hits_t
-- ============================================================================
-- Authoritative memory store (tenant/user/agent) and per-hit retrieval log.
-- Primary keys use PostgreSQL `SERIAL4` shorthand (implicit sequence +
-- NOT NULL + PRIMARY KEY); isolation columns remain varchar for cross-table
-- consistency with `memory_user_config_t`.

CREATE TABLE IF NOT EXISTS nexent.memory_records_t (
    memory_id          SERIAL4 PRIMARY KEY,
    tenant_id          varchar(100),
    user_id            varchar(100),
    agent_id           varchar(100),
    conversation_id    varchar(100),
    layer              varchar(30)  NOT NULL,
    memory_type        varchar(30),
    status             varchar(30)  NOT NULL DEFAULT 'active',
    content            text         NOT NULL,
    concept_tags       text[],
    es_index_name      varchar(255),
    create_time        timestamp DEFAULT CURRENT_TIMESTAMP,
    update_time        timestamp DEFAULT CURRENT_TIMESTAMP,
    created_by         varchar(100),
    updated_by         varchar(100),
    delete_flag        varchar(1)   NOT NULL DEFAULT 'N',
    idempotency_key    varchar(128) NOT NULL,
    recall_count       int4         NOT NULL DEFAULT 0,
    daily_count        int4         NOT NULL DEFAULT 0,
    grounded_count     int4         NOT NULL DEFAULT 0,
    last_recalled_at   timestamp,
    query_hashes       text[],
    recall_days        text[],
    light_hits         int4         NOT NULL DEFAULT 0,
    rem_hits           int4         NOT NULL DEFAULT 0,
    last_light_at      timestamp,
    last_rem_at        timestamp
);
ALTER TABLE nexent.memory_records_t OWNER TO "root";

COMMENT ON COLUMN nexent.memory_records_t.memory_id IS 'Auto-incremented memory primary key (serial4).';
COMMENT ON COLUMN nexent.memory_records_t.tenant_id IS 'Tenant ID (isolation key).';
COMMENT ON COLUMN nexent.memory_records_t.user_id IS 'User ID (isolation key for user/agent layers).';
COMMENT ON COLUMN nexent.memory_records_t.agent_id IS 'Agent ID (isolation key for agent short-term layer).';
COMMENT ON COLUMN nexent.memory_records_t.conversation_id IS 'Conversation ID (further isolation key for agent).';
COMMENT ON COLUMN nexent.memory_records_t.layer IS 'Memory layer: tenant | user | agent.';
COMMENT ON COLUMN nexent.memory_records_t.memory_type IS 'Memory type: long_term | short_term.';
COMMENT ON COLUMN nexent.memory_records_t.status IS 'Status: active | archived | disabled.';
COMMENT ON COLUMN nexent.memory_records_t.content IS 'Memory content.';
COMMENT ON COLUMN nexent.memory_records_t.concept_tags IS 'Optional concept tags from Dreaming REM phase.';
COMMENT ON COLUMN nexent.memory_records_t.es_index_name IS 'Elasticsearch index for agent short-term memory (mem_<model>_<dim>); null for PG-only layers.';
COMMENT ON COLUMN nexent.memory_records_t.create_time IS 'Creation time, audit field.';
COMMENT ON COLUMN nexent.memory_records_t.update_time IS 'Update time, audit field.';
COMMENT ON COLUMN nexent.memory_records_t.created_by IS 'Creator ID, audit field.';
COMMENT ON COLUMN nexent.memory_records_t.updated_by IS 'Last updater ID, audit field.';
COMMENT ON COLUMN nexent.memory_records_t.delete_flag IS 'Soft delete flag (Y/N).';
COMMENT ON COLUMN nexent.memory_records_t.idempotency_key IS 'Idempotency key for write deduplication.';
COMMENT ON COLUMN nexent.memory_records_t.recall_count IS 'Total recall hit count.';
COMMENT ON COLUMN nexent.memory_records_t.daily_count IS 'Recall hit count for the most recent active day.';
COMMENT ON COLUMN nexent.memory_records_t.grounded_count IS 'Count of grounded (verified) recalls.';
COMMENT ON COLUMN nexent.memory_records_t.last_recalled_at IS 'Most recent recall timestamp.';
COMMENT ON COLUMN nexent.memory_records_t.query_hashes IS 'Hashes of queries that recalled this memory.';
COMMENT ON COLUMN nexent.memory_records_t.recall_days IS 'ISO date strings of recall days.';
COMMENT ON COLUMN nexent.memory_records_t.light_hits IS 'Light Sleep phase hit count.';
COMMENT ON COLUMN nexent.memory_records_t.rem_hits IS 'REM Sleep phase hit count.';
COMMENT ON COLUMN nexent.memory_records_t.last_light_at IS 'Last Light Sleep timestamp.';
COMMENT ON COLUMN nexent.memory_records_t.last_rem_at IS 'Last REM Sleep timestamp.';
COMMENT ON TABLE  nexent.memory_records_t IS 'Authoritative store for tenant/user/agent memory (Phase 2).';

CREATE INDEX IF NOT EXISTS idx_memory_records_tenant
    ON nexent.memory_records_t (tenant_id);
CREATE INDEX IF NOT EXISTS idx_memory_records_user
    ON nexent.memory_records_t (tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_memory_records_agent
    ON nexent.memory_records_t (tenant_id, user_id, agent_id, conversation_id);
CREATE INDEX IF NOT EXISTS idx_memory_records_idempotency
    ON nexent.memory_records_t (tenant_id, idempotency_key);
CREATE INDEX IF NOT EXISTS idx_memory_records_status
    ON nexent.memory_records_t (tenant_id, user_id, layer, status);

CREATE TABLE IF NOT EXISTS nexent.memory_retrieval_hits_t (
    hit_id             SERIAL4 PRIMARY KEY,
    tenant_id          varchar(100),
    user_id            varchar(100),
    agent_id           varchar(100),
    conversation_id    varchar(100),
    memory_id          int4,
    query_text         text,
    query_hash         varchar(128),
    retrieval_score    numeric(38, 18),
    source             varchar(100) NOT NULL DEFAULT 'nexent',
    occurred_at        timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    day                varchar(100),
    grounded           boolean NOT NULL DEFAULT false,
    create_time        timestamp DEFAULT CURRENT_TIMESTAMP,
    update_time        timestamp DEFAULT CURRENT_TIMESTAMP,
    created_by         varchar(100),
    updated_by         varchar(100),
    delete_flag        varchar(1)   NOT NULL DEFAULT 'N'
);
ALTER TABLE nexent.memory_retrieval_hits_t OWNER TO "root";

COMMENT ON COLUMN nexent.memory_retrieval_hits_t.hit_id IS 'Hit primary key (serial4).';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.tenant_id IS 'Tenant ID.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.user_id IS 'User ID.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.agent_id IS 'Agent ID.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.conversation_id IS 'Conversation ID.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.memory_id IS 'Recalled memory id (null on miss rows).';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.query_text IS 'Original search query text.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.query_hash IS 'Stable hash of the query text.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.retrieval_score IS 'Similarity score reported by the backend.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.source IS 'Hit origin: nexent | external_provider.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.occurred_at IS 'Time the hit was recorded.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.day IS 'ISO date string (occurred_at::date).';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.grounded IS 'Whether the hit was verified/grounded.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.create_time IS 'Row creation time.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.update_time IS 'Row last update time.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.created_by IS 'User that created the row.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.updated_by IS 'User that last updated the row.';
COMMENT ON COLUMN nexent.memory_retrieval_hits_t.delete_flag IS 'Soft delete flag (N = active, Y = deleted).';
COMMENT ON TABLE  nexent.memory_retrieval_hits_t IS 'Per-hit memory retrieval log; consumed by Dreaming scheduler.';

CREATE INDEX IF NOT EXISTS idx_memory_retrieval_hits_memory
    ON nexent.memory_retrieval_hits_t (memory_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_memory_retrieval_hits_tenant_user_agent
    ON nexent.memory_retrieval_hits_t (tenant_id, user_id, agent_id, day);

CREATE OR REPLACE FUNCTION nexent.update_memory_records_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_memory_records_update_time_trigger ON nexent.memory_records_t;
CREATE TRIGGER update_memory_records_update_time_trigger
BEFORE UPDATE ON nexent.memory_records_t
FOR EACH ROW
EXECUTE FUNCTION nexent.update_memory_records_update_time();

COMMENT ON TRIGGER update_memory_records_update_time_trigger ON nexent.memory_records_t IS 'Trigger to call update_memory_records_update_time function before each update on memory_records_t table';

-- Trigger to keep memory_retrieval_hits_t.update_time fresh on UPDATE.
CREATE OR REPLACE FUNCTION nexent.update_memory_retrieval_hits_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_memory_retrieval_hits_update_time_trigger ON nexent.memory_retrieval_hits_t;
CREATE TRIGGER update_memory_retrieval_hits_update_time_trigger
BEFORE UPDATE ON nexent.memory_retrieval_hits_t
FOR EACH ROW
EXECUTE FUNCTION nexent.update_memory_retrieval_hits_update_time();

COMMENT ON TRIGGER update_memory_retrieval_hits_update_time_trigger ON nexent.memory_retrieval_hits_t IS 'Trigger to call update_memory_retrieval_hits_update_time function before each update on memory_retrieval_hits_t table';
-- Manual Dreaming run audit. Scope concurrency uses PostgreSQL transaction
-- advisory locks, so no persistent lock row is required.
CREATE TABLE IF NOT EXISTS nexent.memory_dreaming_audit_t (
    run_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    agent_id VARCHAR(100) NOT NULL,
    trigger_source VARCHAR(30) NOT NULL DEFAULT 'manual',
    status VARCHAR(30) NOT NULL DEFAULT 'running',
    current_phase VARCHAR(30),
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    light_count INTEGER NOT NULL DEFAULT 0,
    rem_count INTEGER NOT NULL DEFAULT 0,
    promoted_count INTEGER NOT NULL DEFAULT 0,
    deferred_count INTEGER NOT NULL DEFAULT 0,
    result_json JSONB,
    error TEXT,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);
CREATE INDEX IF NOT EXISTS idx_memory_dreaming_audit_scope
    ON nexent.memory_dreaming_audit_t
    (tenant_id, user_id, agent_id, started_at DESC);
