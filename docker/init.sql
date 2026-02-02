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
  "expected_chunk_size" int4,
  "maximum_chunk_size" int4,
  "chunk_batch" int4,
  "display_name" varchar(100) COLLATE "pg_catalog"."default",
  "connect_status" varchar(100) COLLATE "pg_catalog"."default",
  "ssl_verify" boolean DEFAULT true,
  "create_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'::character varying,
  "update_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "updated_by" varchar(100) COLLATE "pg_catalog"."default",
  "created_by" varchar(100) COLLATE "pg_catalog"."default",
  "tenant_id" varchar(100) COLLATE "pg_catalog"."default" DEFAULT 'tenant_id',
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
COMMENT ON COLUMN "model_record_t".expected_chunk_size IS 'Expected chunk size for embedding models, used during document chunking';
COMMENT ON COLUMN "model_record_t".maximum_chunk_size IS 'Maximum chunk size for embedding models, used during document chunking';
COMMENT ON COLUMN "model_record_t"."display_name" IS 'Model name displayed directly in frontend, customized by user';
COMMENT ON COLUMN "model_record_t"."connect_status" IS 'Model connectivity status from last check, optional values: "检测中"、"可用"、"不可用"';
COMMENT ON COLUMN "model_record_t"."ssl_verify" IS 'Whether to verify SSL certificates when connecting to this model API. Default is true. Set to false for local services without SSL support.';
COMMENT ON COLUMN "model_record_t"."create_time" IS 'Creation time, audit field';
COMMENT ON COLUMN "model_record_t"."delete_flag" IS 'When deleted by user frontend, delete flag will be set to true, achieving soft delete effect. Optional values Y/N';
COMMENT ON COLUMN "model_record_t"."update_time" IS 'Update time, audit field';
COMMENT ON COLUMN "model_record_t"."updated_by" IS 'Last updater ID, audit field';
COMMENT ON COLUMN "model_record_t"."created_by" IS 'Creator ID, audit field';
COMMENT ON COLUMN "model_record_t"."tenant_id" IS 'Tenant ID for filtering';
COMMENT ON TABLE "model_record_t" IS 'List of models defined by users in the configuration page';

INSERT INTO "nexent"."model_record_t" ("model_repo", "model_name", "model_factory", "model_type", "api_key", "base_url", "max_tokens", "used_token", "display_name", "connect_status") VALUES ('', 'volcano_tts', 'OpenAI-API-Compatible', 'tts', '', '', 0, 0, 'volcano_tts', 'unavailable');
INSERT INTO "nexent"."model_record_t" ("model_repo", "model_name", "model_factory", "model_type", "api_key", "base_url", "max_tokens", "used_token", "display_name", "connect_status") VALUES ('', 'volcano_stt', 'OpenAI-API-Compatible', 'stt', '', '', 0, 0, 'volcano_stt', 'unavailable');

CREATE TABLE IF NOT EXISTS "knowledge_record_t" (
  "knowledge_id" SERIAL,
  "index_name" varchar(100) COLLATE "pg_catalog"."default",
  "knowledge_name" varchar(100) COLLATE "pg_catalog"."default",
  "knowledge_describe" varchar(3000) COLLATE "pg_catalog"."default",
  "tenant_id" varchar(100) COLLATE "pg_catalog"."default",
  "knowledge_sources" varchar(100) COLLATE "pg_catalog"."default",
  "embedding_model_name" varchar(200) COLLATE "pg_catalog"."default",
  "group_ids" varchar,
  "ingroup_permission" varchar(30),
  "create_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "update_time" timestamp(0) DEFAULT CURRENT_TIMESTAMP,
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'::character varying,
  "updated_by" varchar(100) COLLATE "pg_catalog"."default",
  "created_by" varchar(100) COLLATE "pg_catalog"."default",
  CONSTRAINT "knowledge_record_t_pk" PRIMARY KEY ("knowledge_id")
);
ALTER TABLE "knowledge_record_t" OWNER TO "root";
COMMENT ON COLUMN "knowledge_record_t"."knowledge_id" IS 'Knowledge base ID, unique primary key';
COMMENT ON COLUMN "knowledge_record_t"."index_name" IS 'Internal Elasticsearch index name';
COMMENT ON COLUMN "knowledge_record_t"."knowledge_name" IS 'User-facing knowledge base name (display name), mapped to internal index_name';
COMMENT ON COLUMN "knowledge_record_t"."knowledge_describe" IS 'Knowledge base description';
COMMENT ON COLUMN "knowledge_record_t"."tenant_id" IS 'Tenant ID';
COMMENT ON COLUMN "knowledge_record_t"."knowledge_sources" IS 'Knowledge base sources';
COMMENT ON COLUMN "knowledge_record_t"."embedding_model_name" IS 'Embedding model name, used to record the embedding model used by the knowledge base';
COMMENT ON COLUMN "knowledge_record_t"."group_ids" IS 'Knowledge base group IDs list';
COMMENT ON COLUMN "knowledge_record_t"."ingroup_permission" IS 'In-group permission: EDIT, READ_ONLY, PRIVATE';
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
    origin_name VARCHAR(100),
    class_name VARCHAR(100),
    description VARCHAR,
    source VARCHAR(100),
    author VARCHAR(100),
    usage VARCHAR(100),
    params JSON,
    inputs VARCHAR,
    output_type VARCHAR(100),
    category VARCHAR(100),
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
    display_name VARCHAR(100),
    description VARCHAR,
    business_description VARCHAR,
    author VARCHAR(100),
    model_name VARCHAR(100),
    model_id INTEGER,
    business_logic_model_name VARCHAR(100),
    business_logic_model_id INTEGER,
    max_steps INTEGER,
    duty_prompt TEXT,
    constraint_prompt TEXT,
    few_shots_prompt TEXT,
    parent_agent_id INTEGER,
    tenant_id VARCHAR(100),
    group_ids VARCHAR,
    enabled BOOLEAN DEFAULT FALSE,
    is_new BOOLEAN DEFAULT FALSE,
    provide_run_summary BOOLEAN DEFAULT FALSE,
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
CREATE TRIGGER update_ag_tenant_agent_update_time_trigger
BEFORE UPDATE ON nexent.ag_tenant_agent_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_tenant_agent_update_time();
-- Add comments to the table
COMMENT ON TABLE nexent.ag_tenant_agent_t IS 'Information table for agents';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_tenant_agent_t.agent_id IS 'ID';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.name IS 'Agent name';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.display_name IS 'Agent display name';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.description IS 'Description';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.author IS 'Agent author';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.business_description IS 'Manually entered by the user to describe the entire business process';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.model_name IS '[DEPRECATED] Name of the model used, use model_id instead';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.model_id IS 'Model ID, foreign key reference to model_record_t.model_id';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.business_logic_model_name IS 'Model name used for business logic prompt generation';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.business_logic_model_id IS 'Model ID used for business logic prompt generation, foreign key reference to model_record_t.model_id';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.max_steps IS 'Maximum number of steps';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.duty_prompt IS 'Duty prompt';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.constraint_prompt IS 'Constraint prompt';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.few_shots_prompt IS 'Few-shots prompt';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.parent_agent_id IS 'Parent Agent ID';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.tenant_id IS 'Belonging tenant';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.group_ids IS 'Agent group IDs list';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.enabled IS 'Enable flag';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.provide_run_summary IS 'Whether to provide the running summary to the manager agent';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.is_new IS 'Whether this agent is marked as new for the user';

-- Create index for is_new queries
CREATE INDEX IF NOT EXISTS idx_ag_tenant_agent_t_is_new
ON nexent.ag_tenant_agent_t (tenant_id, is_new)
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
CREATE TRIGGER update_ag_tool_instance_update_time_trigger
BEFORE UPDATE ON nexent.ag_tool_instance_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_tool_instance_update_time();

-- Add comment to the trigger
COMMENT ON TRIGGER update_ag_tool_instance_update_time_trigger ON nexent.ag_tool_instance_t IS 'Trigger to call update_ag_tool_instance_update_time function before each update on ag_tool_instance_t table';

-- Create the tenant_config_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.tenant_config_t (
    tenant_config_id SERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    value_type VARCHAR(100),
    config_key VARCHAR(100),
    config_value TEXT,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- Add comment to the table
COMMENT ON TABLE nexent.tenant_config_t IS 'Tenant configuration information table';

-- Add comments to the columns
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

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_tenant_config_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create a trigger to call the function before each update
CREATE TRIGGER update_tenant_config_update_time_trigger
BEFORE UPDATE ON nexent.tenant_config_t
FOR EACH ROW
EXECUTE FUNCTION update_tenant_config_update_time();

-- Create the mcp_record_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.mcp_record_t (
    mcp_id SERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    mcp_name VARCHAR(100),
    mcp_server VARCHAR(500),
    status BOOLEAN DEFAULT NULL,
    container_id VARCHAR(200) DEFAULT NULL,
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
COMMENT ON COLUMN nexent.mcp_record_t.status IS 'MCP server connection status, true=connected, false=disconnected, null=unknown';
COMMENT ON COLUMN nexent.mcp_record_t.container_id IS 'Docker container ID for MCP service, NULL for non-containerized MCP';
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
    user_role VARCHAR(30) DEFAULT 'USER',
    user_email VARCHAR(255),
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
COMMENT ON COLUMN nexent.user_tenant_t.user_role IS 'User role: SUPER_ADMIN, ADMIN, DEV, USER';
COMMENT ON COLUMN nexent.user_tenant_t.user_email IS 'User email address';
COMMENT ON COLUMN nexent.user_tenant_t.create_time IS 'Create time';
COMMENT ON COLUMN nexent.user_tenant_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.user_tenant_t.created_by IS 'Created by';
COMMENT ON COLUMN nexent.user_tenant_t.updated_by IS 'Updated by';
COMMENT ON COLUMN nexent.user_tenant_t.delete_flag IS 'Delete flag, Y/N';

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
COMMENT ON COLUMN nexent.ag_agent_relation_t.delete_flag IS 'Delete flag, set to Y for soft delete, optional values Y/N';

-- Create user memory config table
CREATE TABLE IF NOT EXISTS "memory_user_config_t" (
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
  "delete_flag" varchar(1) COLLATE "pg_catalog"."default" DEFAULT 'N'
);

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

CREATE TRIGGER "update_memory_user_config_update_time_trigger"
BEFORE UPDATE ON "nexent"."memory_user_config_t"
FOR EACH ROW
EXECUTE FUNCTION "update_memory_user_config_update_time"();

-- Create partner mapping id table
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

CREATE TRIGGER "update_partner_mapping_update_time_trigger"
BEFORE UPDATE ON "nexent"."partner_mapping_id_t"
FOR EACH ROW
EXECUTE FUNCTION "update_partner_mapping_update_time"();

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

-- Add primary key constraint for role_permission_t table
ALTER TABLE nexent.role_permission_t ADD CONSTRAINT role_permission_t_pkey PRIMARY KEY (role_permission_id);


-- Insert role permission data with conflict handling
INSERT INTO nexent.role_permission_t (role_permission_id, user_role, permission_category, permission_type, permission_subtype) VALUES
(1, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/'),
(2, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/space'),
(3, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/knowledges'),
(4, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/mcp-tools'),
(5, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/monitoring'),
(6, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/models'),
(7, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/memory'),
(8, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/users'),
(211, 'SU', 'VISIBILITY', 'LEFT_NAV_MENU', '/tenant-resources'),
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
(212, 'ADMIN', 'VISIBILITY', 'LEFT_NAV_MENU', '/tenant-resources'),
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

-- Insert SPEED role user into user_tenant_t table if not exists
INSERT INTO nexent.user_tenant_t (user_id, tenant_id, user_role, user_email, created_by, updated_by)
VALUES ('user_id', 'tenant_id', 'SPEED', NULL, 'system', 'system')
ON CONFLICT (user_id, tenant_id) DO NOTHING;
