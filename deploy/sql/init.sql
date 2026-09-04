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

CREATE TABLE IF NOT EXISTS "knowledge_storage_object_t" (
  "storage_object_id" BIGSERIAL,
  "tenant_id" varchar(100) NOT NULL,
  "knowledge_id" BIGINT NOT NULL,
  "index_name" varchar(100) NOT NULL,
  "bucket_name" varchar(255) NOT NULL,
  "object_name" varchar(1024) NOT NULL,
  "raw_bytes" BIGINT NOT NULL,
  "status" varchar(20) NOT NULL DEFAULT 'COMMITTED',
  "create_time" timestamp(0) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "update_time" timestamp(0) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "created_by" varchar(100),
  "updated_by" varchar(100),
  "delete_flag" varchar(1) NOT NULL DEFAULT 'N',
  CONSTRAINT "knowledge_storage_object_t_pk" PRIMARY KEY ("storage_object_id"),
  CONSTRAINT "uq_knowledge_storage_object_bucket_object" UNIQUE ("bucket_name", "object_name"),
  CONSTRAINT "ck_knowledge_storage_object_raw_bytes_nonnegative" CHECK ("raw_bytes" >= 0),
  CONSTRAINT "ck_knowledge_storage_object_status" CHECK ("status" IN ('COMMITTED', 'DELETED'))
);
ALTER TABLE "knowledge_storage_object_t" OWNER TO "root";
COMMENT ON TABLE "knowledge_storage_object_t" IS 'Durable ownership and accounting ledger for retained knowledge-base source objects';
COMMENT ON COLUMN "knowledge_storage_object_t"."storage_object_id" IS 'Storage object ledger ID';
COMMENT ON COLUMN "knowledge_storage_object_t"."tenant_id" IS 'Tenant isolation key';
COMMENT ON COLUMN "knowledge_storage_object_t"."knowledge_id" IS 'Owning knowledge base ID';
COMMENT ON COLUMN "knowledge_storage_object_t"."index_name" IS 'Owning Elasticsearch index name';
COMMENT ON COLUMN "knowledge_storage_object_t"."bucket_name" IS 'MinIO bucket name';
COMMENT ON COLUMN "knowledge_storage_object_t"."object_name" IS 'MinIO object name';
COMMENT ON COLUMN "knowledge_storage_object_t"."raw_bytes" IS 'Authoritative MinIO object size in bytes';
COMMENT ON COLUMN "knowledge_storage_object_t"."status" IS 'Accounting lifecycle status: COMMITTED or DELETED';
COMMENT ON COLUMN "knowledge_storage_object_t"."create_time" IS 'Creation time, audit field';
COMMENT ON COLUMN "knowledge_storage_object_t"."update_time" IS 'Update time, audit field';
COMMENT ON COLUMN "knowledge_storage_object_t"."created_by" IS 'Creator ID, audit field';
COMMENT ON COLUMN "knowledge_storage_object_t"."updated_by" IS 'Last updater ID, audit field';
COMMENT ON COLUMN "knowledge_storage_object_t"."delete_flag" IS 'Soft delete flag: N or Y';
CREATE INDEX IF NOT EXISTS "idx_knowledge_storage_object_tenant_active"
  ON "knowledge_storage_object_t" ("tenant_id")
  WHERE "delete_flag" = 'N' AND "status" = 'COMMITTED';
CREATE INDEX IF NOT EXISTS "idx_knowledge_storage_object_kb_active"
  ON "knowledge_storage_object_t" ("tenant_id", "knowledge_id")
  WHERE "delete_flag" = 'N' AND "status" = 'COMMITTED';

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

-- Unified tag management final schema. Legacy data migration remains in the
-- versioned v2.5.2 migration and is intentionally not duplicated here.
CREATE TABLE IF NOT EXISTS nexent.tag_bucket (
    bucket_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    bucket_key VARCHAR(100) NOT NULL,
    bucket_name VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y')),
    CONSTRAINT uq_tag_bucket_tenant_id UNIQUE (tenant_id, bucket_id),
    CONSTRAINT uq_tag_bucket_tenant_key UNIQUE (tenant_id, bucket_key)
);

CREATE TABLE IF NOT EXISTS nexent.tag_bucket_resource_type (
    bucket_resource_type_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    bucket_id BIGINT NOT NULL,
    resource_type VARCHAR(50) NOT NULL CHECK (
        resource_type IN ('agent', 'skill', 'tool', 'mcp_service', 'knowledge_base', 'knowledge_document')
    ),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y')),
    CONSTRAINT uq_tag_bucket_resource_type_tenant_id UNIQUE (tenant_id, bucket_resource_type_id),
    CONSTRAINT uq_tag_bucket_resource_type UNIQUE (tenant_id, bucket_id, resource_type),
    CONSTRAINT fk_tag_bucket_resource_type_bucket
        FOREIGN KEY (tenant_id, bucket_id)
        REFERENCES nexent.tag_bucket (tenant_id, bucket_id)
);

CREATE TABLE IF NOT EXISTS nexent.tag_definition (
    definition_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    bucket_id BIGINT NOT NULL,
    definition_key VARCHAR(100) NOT NULL,
    definition_name VARCHAR(255) NOT NULL,
    normalized_name TEXT COLLATE "C" GENERATED ALWAYS AS (
        lower(btrim(definition_name) COLLATE "C")
    ) STORED,
    selection_mode VARCHAR(20) NOT NULL CHECK (selection_mode IN ('single_select', 'multi_select', 'no_value')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y')),
    CONSTRAINT uq_tag_definition_tenant_id UNIQUE (tenant_id, definition_id),
    CONSTRAINT fk_tag_definition_bucket
        FOREIGN KEY (tenant_id, bucket_id)
        REFERENCES nexent.tag_bucket (tenant_id, bucket_id)
);

CREATE TABLE IF NOT EXISTS nexent.tag_value (
    value_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    definition_id BIGINT NOT NULL,
    normalized_value TEXT NOT NULL CHECK (btrim(normalized_value) <> ''),
    display_value TEXT NOT NULL CHECK (btrim(display_value) <> ''),
    sort_order INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y')),
    CONSTRAINT uq_tag_value_tenant_id_definition UNIQUE (tenant_id, value_id, definition_id),
    CONSTRAINT fk_tag_value_definition
        FOREIGN KEY (tenant_id, definition_id)
        REFERENCES nexent.tag_definition (tenant_id, definition_id)
);

CREATE TABLE IF NOT EXISTS nexent.resource_tag_assignment (
    assignment_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    resource_type VARCHAR(50) NOT NULL CHECK (
        resource_type IN ('agent', 'skill', 'tool', 'mcp_service', 'knowledge_base', 'knowledge_document')
    ),
    resource_id TEXT NOT NULL CHECK (btrim(resource_id) <> ''),
    definition_id BIGINT NOT NULL,
    value_id BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N' CHECK (delete_flag IN ('N', 'Y')),
    CONSTRAINT uq_resource_tag_assignment_tenant_id UNIQUE (tenant_id, assignment_id),
    CONSTRAINT uq_resource_tag_assignment_resource_value
        UNIQUE (tenant_id, resource_type, resource_id, value_id),
    CONSTRAINT fk_resource_tag_assignment_definition
        FOREIGN KEY (tenant_id, definition_id)
        REFERENCES nexent.tag_definition (tenant_id, definition_id),
    CONSTRAINT fk_resource_tag_assignment_value_definition
        FOREIGN KEY (tenant_id, value_id, definition_id)
        REFERENCES nexent.tag_value (tenant_id, value_id, definition_id)
);

CREATE INDEX IF NOT EXISTS idx_tag_definition_bucket
    ON nexent.tag_definition (tenant_id, bucket_id, delete_flag);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tag_definition_active_key
    ON nexent.tag_definition (tenant_id, bucket_id, definition_key)
    WHERE delete_flag = 'N';
CREATE UNIQUE INDEX IF NOT EXISTS uq_tag_definition_active_normalized_name
    ON nexent.tag_definition (tenant_id, bucket_id, normalized_name)
    WHERE delete_flag = 'N';
CREATE INDEX IF NOT EXISTS idx_tag_value_definition
    ON nexent.tag_value (tenant_id, definition_id, delete_flag);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tag_value_active_normalized_value
    ON nexent.tag_value (tenant_id, definition_id, normalized_value)
    WHERE delete_flag = 'N';
CREATE INDEX IF NOT EXISTS idx_resource_tag_assignment_resource
    ON nexent.resource_tag_assignment (tenant_id, resource_type, resource_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_resource_tag_assignment_definition
    ON nexent.resource_tag_assignment (tenant_id, definition_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_resource_tag_assignment_value
    ON nexent.resource_tag_assignment (tenant_id, value_id, delete_flag)
    WHERE delete_flag = 'N';

CREATE TABLE IF NOT EXISTS nexent.document_tag_projection (
    projection_id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL CHECK (btrim(tenant_id) <> ''),
    provider VARCHAR(20) NOT NULL CHECK (provider IN ('local', 'aidp')),
    knowledge_base_id VARCHAR(255) NOT NULL CHECK (btrim(knowledge_base_id) <> ''),
    provider_document_id VARCHAR(512) NOT NULL CHECK (btrim(provider_document_id) <> ''),
    resource_id TEXT NOT NULL CHECK (btrim(resource_id) <> ''),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'synced', 'failed', 'unsupported')),
    version BIGINT NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '[]'::JSONB,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_attempt_at TIMESTAMP WITH TIME ZONE,
    next_attempt_at TIMESTAMP WITH TIME ZONE,
    create_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    CONSTRAINT uq_document_tag_projection_identity
        UNIQUE (tenant_id, provider, knowledge_base_id, provider_document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_tag_projection_tenant_status
    ON nexent.document_tag_projection (tenant_id, status, next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_document_tag_projection_kb
    ON nexent.document_tag_projection (tenant_id, provider, knowledge_base_id);

CREATE INDEX IF NOT EXISTS idx_document_tag_projection_resource
    ON nexent.document_tag_projection (tenant_id, resource_id);

CREATE OR REPLACE FUNCTION nexent.provision_unified_tag_management(
    p_tenant_id VARCHAR,
    p_actor VARCHAR DEFAULT 'system'
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_default_bucket_id BIGINT;
    v_document_bucket_id BIGINT;
BEGIN
    IF p_tenant_id IS NULL OR btrim(p_tenant_id) = '' THEN
        RAISE EXCEPTION 'Cannot provision unified tags for an empty tenant';
    END IF;

    INSERT INTO nexent.tag_bucket (
        tenant_id, bucket_key, bucket_name, status, created_by, updated_by, delete_flag
    ) VALUES (
        p_tenant_id, 'default_resource', 'Default Resource', 'active', p_actor, p_actor, 'N'
    )
    ON CONFLICT (tenant_id, bucket_key) DO UPDATE
    SET bucket_name = EXCLUDED.bucket_name,
        status = 'active',
        update_time = CURRENT_TIMESTAMP,
        updated_by = EXCLUDED.updated_by,
        delete_flag = 'N'
    RETURNING bucket_id INTO v_default_bucket_id;

    INSERT INTO nexent.tag_bucket (
        tenant_id, bucket_key, bucket_name, status, created_by, updated_by, delete_flag
    ) VALUES (
        p_tenant_id, 'knowledge_content', 'Knowledge Content', 'active', p_actor, p_actor, 'N'
    )
    ON CONFLICT (tenant_id, bucket_key) DO UPDATE
    SET bucket_name = EXCLUDED.bucket_name,
        status = 'active',
        update_time = CURRENT_TIMESTAMP,
        updated_by = EXCLUDED.updated_by,
        delete_flag = 'N'
    RETURNING bucket_id INTO v_document_bucket_id;

    INSERT INTO nexent.tag_bucket_resource_type (
        tenant_id, bucket_id, resource_type, status, created_by, updated_by, delete_flag
    )
    SELECT p_tenant_id, v_default_bucket_id, resource_type, 'active', p_actor, p_actor, 'N'
    FROM (VALUES ('agent'), ('skill'), ('tool'), ('mcp_service'), ('knowledge_base')) AS types(resource_type)
    ON CONFLICT (tenant_id, bucket_id, resource_type) DO UPDATE
    SET status = 'active', update_time = CURRENT_TIMESTAMP, updated_by = EXCLUDED.updated_by, delete_flag = 'N';

    INSERT INTO nexent.tag_bucket_resource_type (
        tenant_id, bucket_id, resource_type, status, created_by, updated_by, delete_flag
    ) VALUES (
        p_tenant_id, v_document_bucket_id, 'knowledge_document', 'active', p_actor, p_actor, 'N'
    )
    ON CONFLICT (tenant_id, bucket_id, resource_type) DO UPDATE
    SET status = 'active', update_time = CURRENT_TIMESTAMP, updated_by = EXCLUDED.updated_by, delete_flag = 'N';
    -- Seed the "Agent Category" multi-select definition in the default resource
    -- bucket plus its 20 preset values so new tenants can use the unified tag
    -- library in the agent repository publish flow. Stable keys are stored as
    -- normalized_value/display_value; the frontend resolves localized labels
    -- via i18n while AgentRepository.tags stays locale-stable for display.
    INSERT INTO nexent.tag_definition (
        tenant_id, bucket_id, definition_key, definition_name, selection_mode,
        sort_order, status, created_by, updated_by, delete_flag
    ) VALUES (
        p_tenant_id, v_default_bucket_id, 'agent_category', 'Agent Category',
        'multi_select', 1, 'active', p_actor, p_actor, 'N'
    )
    ON CONFLICT (tenant_id, bucket_id, definition_key) WHERE delete_flag = 'N' DO UPDATE
    SET definition_name = EXCLUDED.definition_name,
        selection_mode = EXCLUDED.selection_mode,
        status = 'active',
        sort_order = EXCLUDED.sort_order,
        update_time = CURRENT_TIMESTAMP,
        updated_by = EXCLUDED.updated_by,
        delete_flag = 'N';

    INSERT INTO nexent.tag_value (
        tenant_id, definition_id, normalized_value, display_value, sort_order,
        status, created_by, updated_by, delete_flag
    )
    SELECT p_tenant_id, td.definition_id, preset.normalized_value,
           preset.display_value, preset.sort_order, 'active', p_actor, p_actor, 'N'
    FROM nexent.tag_definition AS td
    CROSS JOIN (VALUES
        ('marketing', 'marketing', 0),
        ('copywriting', 'copywriting', 1),
        ('content_creation', 'content_creation', 2),
        ('code_review', 'code_review', 3),
        ('quality', 'quality', 4),
        ('devops', 'devops', 5),
        ('data', 'data', 6),
        ('visualization', 'visualization', 7),
        ('bi', 'bi', 8),
        ('customer_service', 'customer_service', 9),
        ('ticket', 'ticket', 10),
        ('automation', 'automation', 11),
        ('meeting', 'meeting', 12),
        ('minutes', 'minutes', 13),
        ('productivity', 'productivity', 14),
        ('design', 'design', 15),
        ('color_scheme', 'color_scheme', 16),
        ('inspiration', 'inspiration', 17),
        ('spreadsheet', 'spreadsheet', 18),
        ('office', 'office', 19)
    ) AS preset(normalized_value, display_value, sort_order)
    WHERE td.tenant_id = p_tenant_id
      AND td.bucket_id = v_default_bucket_id
      AND td.definition_key = 'agent_category'
      AND td.delete_flag = 'N'
    ON CONFLICT (tenant_id, definition_id, normalized_value) WHERE delete_flag = 'N' DO UPDATE
    SET display_value = EXCLUDED.display_value,
        status = 'active',
        sort_order = EXCLUDED.sort_order,
        update_time = CURRENT_TIMESTAMP,
        updated_by = EXCLUDED.updated_by,
        delete_flag = 'N';
END;
$$;

CREATE OR REPLACE FUNCTION nexent.provision_unified_tag_management_after_user_tenant_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(NEW.delete_flag, 'N') <> 'Y' THEN
        PERFORM nexent.provision_unified_tag_management(NEW.tenant_id, COALESCE(NEW.created_by, 'system'));
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION nexent.enforce_tag_definition_limit()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('tag-definition:' || NEW.tenant_id || ':' || NEW.bucket_id, 0));
    IF NEW.delete_flag <> 'Y' THEN
        SELECT count(*) INTO v_count
        FROM nexent.tag_definition
        WHERE tenant_id = NEW.tenant_id
          AND bucket_id = NEW.bucket_id
          AND delete_flag <> 'Y'
          AND definition_id <> COALESCE(NEW.definition_id, -1);
        IF v_count >= 100 THEN
            RAISE EXCEPTION 'Tag definition limit exceeded for tenant %, bucket % (maximum 100)',
                NEW.tenant_id, NEW.bucket_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION nexent.enforce_tag_value_limit()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('tag-value:' || NEW.tenant_id || ':' || NEW.definition_id, 0));
    IF NEW.delete_flag <> 'Y' THEN
        SELECT count(*) INTO v_count
        FROM nexent.tag_value
        WHERE tenant_id = NEW.tenant_id
          AND definition_id = NEW.definition_id
          AND delete_flag <> 'Y'
          AND value_id <> COALESCE(NEW.value_id, -1);
        IF v_count >= 1000 THEN
            RAISE EXCEPTION 'Tag value limit exceeded for tenant %, definition % (maximum 1000)',
                NEW.tenant_id, NEW.definition_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION nexent.enforce_resource_tag_assignment_rules()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
    v_selection_mode VARCHAR(20);
    v_bucket_id BIGINT;
    v_validate_active_reference BOOLEAN;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended('tag-assignment:' || NEW.tenant_id || ':' || NEW.resource_type || ':' || NEW.resource_id, 0)
    );

    IF TG_OP = 'INSERT' THEN
        v_validate_active_reference := TRUE;
    ELSIF NEW.delete_flag <> 'Y' THEN
        v_validate_active_reference := OLD.delete_flag = 'Y'
                OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
                OR OLD.resource_type IS DISTINCT FROM NEW.resource_type
                OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
                OR OLD.definition_id IS DISTINCT FROM NEW.definition_id
                OR OLD.value_id IS DISTINCT FROM NEW.value_id;
    ELSE
        v_validate_active_reference := FALSE;
    END IF;

    IF TG_OP = 'INSERT' OR NEW.delete_flag <> 'Y' THEN
        SELECT definition.selection_mode, definition.bucket_id
        INTO v_selection_mode, v_bucket_id
        FROM nexent.tag_definition AS definition
        JOIN nexent.tag_value AS value
          ON value.tenant_id = definition.tenant_id
         AND value.definition_id = definition.definition_id
         AND value.value_id = NEW.value_id
        WHERE definition.tenant_id = NEW.tenant_id
          AND definition.definition_id = NEW.definition_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Assignment references a mismatched definition/value for tenant %', NEW.tenant_id;
        END IF;

        IF v_validate_active_reference THEN
            IF NOT EXISTS (
                SELECT 1
                FROM nexent.tag_definition AS definition
                JOIN nexent.tag_value AS value
                  ON value.tenant_id = definition.tenant_id
                 AND value.definition_id = definition.definition_id
                 AND value.value_id = NEW.value_id
                 AND value.status = 'active'
                 AND value.delete_flag = 'N'
                WHERE definition.tenant_id = NEW.tenant_id
                  AND definition.definition_id = NEW.definition_id
                  AND definition.status = 'active'
                  AND definition.delete_flag = 'N'
            ) THEN
                RAISE EXCEPTION 'New assignment requires an active definition/value for tenant %', NEW.tenant_id;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM nexent.tag_bucket_resource_type
                WHERE tenant_id = NEW.tenant_id
                  AND bucket_id = v_bucket_id
                  AND resource_type = NEW.resource_type
                  AND status = 'active'
                  AND delete_flag = 'N'
            ) THEN
                RAISE EXCEPTION 'Resource type % requires an active binding to bucket % for tenant %',
                    NEW.resource_type, v_bucket_id, NEW.tenant_id;
            END IF;
        END IF;
    END IF;

    IF NEW.delete_flag <> 'Y' THEN
        SELECT count(*) INTO v_count
        FROM nexent.resource_tag_assignment
        WHERE tenant_id = NEW.tenant_id
          AND resource_type = NEW.resource_type
          AND resource_id = NEW.resource_id
          AND delete_flag <> 'Y'
          AND assignment_id <> COALESCE(NEW.assignment_id, -1);
        IF v_count >= 100 THEN
            RAISE EXCEPTION 'Tag assignment limit exceeded for tenant %, resource %/% (maximum 100)',
                NEW.tenant_id, NEW.resource_type, NEW.resource_id;
        END IF;

        IF v_selection_mode = 'single_select' AND EXISTS (
            SELECT 1
            FROM nexent.resource_tag_assignment
            WHERE tenant_id = NEW.tenant_id
              AND resource_type = NEW.resource_type
              AND resource_id = NEW.resource_id
              AND definition_id = NEW.definition_id
              AND delete_flag <> 'Y'
              AND assignment_id <> COALESCE(NEW.assignment_id, -1)
        ) THEN
            RAISE EXCEPTION 'single_select definition % already has a value for tenant %, resource %/%',
                NEW.definition_id, NEW.tenant_id, NEW.resource_type, NEW.resource_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS enforce_tag_definition_limit_trigger ON nexent.tag_definition;
CREATE TRIGGER enforce_tag_definition_limit_trigger
BEFORE INSERT OR UPDATE ON nexent.tag_definition
FOR EACH ROW EXECUTE FUNCTION nexent.enforce_tag_definition_limit();

DROP TRIGGER IF EXISTS enforce_tag_value_limit_trigger ON nexent.tag_value;
CREATE TRIGGER enforce_tag_value_limit_trigger
BEFORE INSERT OR UPDATE ON nexent.tag_value
FOR EACH ROW EXECUTE FUNCTION nexent.enforce_tag_value_limit();

DROP TRIGGER IF EXISTS enforce_resource_tag_assignment_rules_trigger ON nexent.resource_tag_assignment;
CREATE TRIGGER enforce_resource_tag_assignment_rules_trigger
BEFORE INSERT OR UPDATE ON nexent.resource_tag_assignment
FOR EACH ROW EXECUTE FUNCTION nexent.enforce_resource_tag_assignment_rules();

DO $$
BEGIN
    IF to_regclass('nexent.user_tenant_t') IS NOT NULL THEN
        EXECUTE 'DROP TRIGGER IF EXISTS provision_unified_tag_management_trigger ON nexent.user_tenant_t';
        EXECUTE 'CREATE TRIGGER provision_unified_tag_management_trigger
                 AFTER INSERT ON nexent.user_tenant_t
                 FOR EACH ROW
                 EXECUTE FUNCTION nexent.provision_unified_tag_management_after_user_tenant_insert()';
    END IF;
END;
$$;
