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
    agent_id SERIAL NOT NULL,
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
    version_no INTEGER DEFAULT 0 NOT NULL,
    current_version_no INTEGER NULL,
    ingroup_permission VARCHAR(30),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    PRIMARY KEY (agent_id, version_no)
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
COMMENT ON COLUMN nexent.ag_tenant_agent_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.current_version_no IS 'Current published version number. NULL means no version published yet';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.ingroup_permission IS 'In-group permission: EDIT, READ_ONLY, PRIVATE';

-- Create index for is_new queries
CREATE INDEX IF NOT EXISTS idx_ag_tenant_agent_t_is_new
ON nexent.ag_tenant_agent_t (tenant_id, is_new)
WHERE delete_flag = 'N';


-- Create the ag_tool_instance_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.ag_tool_instance_t (
    tool_instance_id SERIAL NOT NULL,
    tool_id INTEGER,
    agent_id INTEGER,
    params JSON,
    user_id VARCHAR(100),
    tenant_id VARCHAR(100),
    enabled BOOLEAN DEFAULT FALSE,
    version_no INTEGER DEFAULT 0 NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    PRIMARY KEY (tool_instance_id, version_no)
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
COMMENT ON COLUMN nexent.ag_tool_instance_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';
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
    authorization_token VARCHAR(500) DEFAULT NULL,
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
COMMENT ON COLUMN nexent.mcp_record_t.authorization_token IS 'Authorization token for MCP server authentication (e.g., Bearer token)';
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
    relation_id SERIAL NOT NULL,
    selected_agent_id INTEGER,
    parent_agent_id INTEGER,
    tenant_id VARCHAR(100),
    version_no INTEGER DEFAULT 0 NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    PRIMARY KEY (relation_id, version_no)
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
COMMENT ON COLUMN nexent.ag_agent_relation_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';
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

-- 5. Create role_permission_t table for role permissions
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

-- 6. Insert role permission data after clearing old data
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
(187, 'SPEED', 'RESOURCE', 'TENANT.INVITE', 'DELETE');

-- Insert SPEED role user into user_tenant_t table if not exists
INSERT INTO nexent.user_tenant_t (user_id, tenant_id, user_role, user_email, created_by, updated_by)
VALUES ('user_id', 'tenant_id', 'SPEED', '', 'system', 'system')
ON CONFLICT (user_id, tenant_id) DO NOTHING;

-- Create the ag_tenant_agent_version_t table for agent version management
CREATE TABLE IF NOT EXISTS nexent.ag_tenant_agent_version_t (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    agent_id INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
    version_name VARCHAR(100),
    release_note TEXT,
    source_version_no INTEGER NULL,
    source_type VARCHAR(30) NULL,
    status VARCHAR(30) DEFAULT 'RELEASED',
    created_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_tenant_agent_version_t OWNER TO "root";

-- Add comments for version fields in existing tables
COMMENT ON COLUMN nexent.ag_tenant_agent_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.current_version_no IS 'Current published version number. NULL means no version published yet';
COMMENT ON COLUMN nexent.ag_tool_instance_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';
COMMENT ON COLUMN nexent.ag_agent_relation_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';

-- Add comments for ag_tenant_agent_version_t table
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

-- Create the user_token_info_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.user_token_info_t (
    token_id SERIAL4 PRIMARY KEY NOT NULL,
    access_key VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE "user_token_info_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.user_token_info_t IS 'User token (AK/SK) information table';

-- Add comments to the columns
COMMENT ON COLUMN nexent.user_token_info_t.token_id IS 'Token ID, unique primary key';
COMMENT ON COLUMN nexent.user_token_info_t.access_key IS 'Access Key (AK)';
COMMENT ON COLUMN nexent.user_token_info_t.user_id IS 'User ID who owns this token';
COMMENT ON COLUMN nexent.user_token_info_t.create_time IS 'Creation time, audit field';
COMMENT ON COLUMN nexent.user_token_info_t.update_time IS 'Update time, audit field';
COMMENT ON COLUMN nexent.user_token_info_t.created_by IS 'Creator ID, audit field';
COMMENT ON COLUMN nexent.user_token_info_t.updated_by IS 'Last updater ID, audit field';
COMMENT ON COLUMN nexent.user_token_info_t.delete_flag IS 'Soft delete flag, Y means deleted';


-- Create the user_token_usage_log_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.user_token_usage_log_t (
    token_usage_id SERIAL4 PRIMARY KEY NOT NULL,
    token_id INT4 NOT NULL,
    call_function_name VARCHAR(100),
    related_id INT4,
    meta_data JSONB,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE "user_token_usage_log_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.user_token_usage_log_t IS 'User token usage log table';

-- Add comments to the columns
COMMENT ON COLUMN nexent.user_token_usage_log_t.token_usage_id IS 'Token usage log ID, unique primary key';
COMMENT ON COLUMN nexent.user_token_usage_log_t.token_id IS 'Foreign key to user_token_info_t.token_id';
COMMENT ON COLUMN nexent.user_token_usage_log_t.call_function_name IS 'API function name being called';
COMMENT ON COLUMN nexent.user_token_usage_log_t.related_id IS 'Related resource ID (e.g., conversation_id)';
COMMENT ON COLUMN nexent.user_token_usage_log_t.meta_data IS 'Additional metadata for this usage log entry, stored as JSON';
COMMENT ON COLUMN nexent.user_token_usage_log_t.create_time IS 'Creation time, audit field';
COMMENT ON COLUMN nexent.user_token_usage_log_t.update_time IS 'Update time, audit field';
COMMENT ON COLUMN nexent.user_token_usage_log_t.created_by IS 'Creator ID, audit field';
COMMENT ON COLUMN nexent.user_token_usage_log_t.updated_by IS 'Last updater ID, audit field';
COMMENT ON COLUMN nexent.user_token_usage_log_t.delete_flag IS 'Soft delete flag, Y means deleted';

-- Create the ag_skill_info_t table in the nexent schema
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

ALTER TABLE "ag_skill_info_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.ag_skill_info_t IS 'Skill information table for managing custom skills';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_id IS 'Skill ID, unique primary key';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_name IS 'Skill name, globally unique';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_description IS 'Skill description text';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_tags IS 'Skill tags stored as JSON array';
COMMENT ON COLUMN nexent.ag_skill_info_t.skill_content IS 'Skill content or prompt text';
COMMENT ON COLUMN nexent.ag_skill_info_t.params IS 'Skill configuration parameters stored as JSON object';
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

-- Create the ag_outer_api_services table for OpenAPI services (MCP conversion)
-- This table stores one record per MCP service instead of per tool
CREATE TABLE IF NOT EXISTS nexent.ag_outer_api_services (
    id BIGSERIAL PRIMARY KEY,
    mcp_service_name VARCHAR(100) NOT NULL,
    description TEXT,
    openapi_json JSONB,
    server_url VARCHAR(500),
    headers_template JSONB,
    tenant_id VARCHAR(100) NOT NULL,
    is_available BOOLEAN DEFAULT TRUE,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_outer_api_services OWNER TO "root";

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_ag_outer_api_services_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create a trigger to call the function before each update
CREATE TRIGGER update_ag_outer_api_services_update_time_trigger
BEFORE UPDATE ON nexent.ag_outer_api_services
FOR EACH ROW
EXECUTE FUNCTION update_ag_outer_api_services_update_time();

-- Add comment to the table
COMMENT ON TABLE nexent.ag_outer_api_services IS 'OpenAPI services table - stores MCP service information converted from OpenAPI specs. One record per service.';

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_outer_api_services.id IS 'Service ID, unique primary key';
COMMENT ON COLUMN nexent.ag_outer_api_services.mcp_service_name IS 'MCP service name (unique identifier per tenant)';
COMMENT ON COLUMN nexent.ag_outer_api_services.description IS 'Service description from OpenAPI info';
COMMENT ON COLUMN nexent.ag_outer_api_services.openapi_json IS 'Complete OpenAPI JSON specification';
COMMENT ON COLUMN nexent.ag_outer_api_services.server_url IS 'Base URL of the REST API server';
COMMENT ON COLUMN nexent.ag_outer_api_services.headers_template IS 'Default headers template as JSONB';
COMMENT ON COLUMN nexent.ag_outer_api_services.tenant_id IS 'Tenant ID for multi-tenancy';
COMMENT ON COLUMN nexent.ag_outer_api_services.is_available IS 'Whether the service is available';
COMMENT ON COLUMN nexent.ag_outer_api_services.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_outer_api_services.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_outer_api_services.created_by IS 'Creator';
COMMENT ON COLUMN nexent.ag_outer_api_services.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.ag_outer_api_services.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create index for tenant_id queries
CREATE INDEX IF NOT EXISTS idx_ag_outer_api_services_tenant_id
ON nexent.ag_outer_api_services (tenant_id)
WHERE delete_flag = 'N';

-- Create index for mcp_service_name queries
CREATE INDEX IF NOT EXISTS idx_ag_outer_api_services_mcp_service_name
ON nexent.ag_outer_api_services (mcp_service_name)
WHERE delete_flag = 'N';

CREATE TABLE IF NOT EXISTS nexent.ag_a2a_nacos_config_t (
    id BIGSERIAL PRIMARY KEY,
    config_id VARCHAR(64) UNIQUE NOT NULL,

    nacos_addr VARCHAR(512) NOT NULL,
    nacos_username VARCHAR(100),
    nacos_password VARCHAR(256),

    namespace_id VARCHAR(100) DEFAULT 'public',

    name VARCHAR(100) NOT NULL,
    description TEXT,

    tenant_id VARCHAR(100) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100),

    is_active BOOLEAN DEFAULT TRUE,
    last_scan_at TIMESTAMP(6),

    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_a2a_nacos_config_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_nacos_config_t IS 'Nacos configuration for external A2A agent discovery. Stores connection info and discovery scope.';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.id IS 'Primary key, auto-increment'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.config_id IS 'Unique config identifier for API reference';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.nacos_addr IS 'Nacos server address, e.g., http://nacos-server:8848';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.nacos_username IS 'Nacos username for authentication';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.nacos_password IS 'Nacos password, encrypted at rest';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.namespace_id IS 'Nacos namespace for service discovery, default is public';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.name IS 'Display name for this Nacos config, e.g., Production Nacos';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.description IS 'Description of this Nacos configuration';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.tenant_id IS 'Tenant ID for multi-tenancy isolation'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.created_by IS 'User who created this config';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.updated_by IS 'User who last updated this record'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.is_active IS 'Whether this Nacos config is active';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.last_scan_at IS 'Last time a scan was performed using this config';
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.create_time IS 'Record creation timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.update_time IS 'Record last update timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_nacos_config_t.delete_flag IS 'Soft delete flag: Y/N';  -- NOSONAR


CREATE TABLE IF NOT EXISTS nexent.ag_a2a_external_agent_t (
    id BIGSERIAL PRIMARY KEY,

    name VARCHAR(255) NOT NULL,
    description TEXT,
    version VARCHAR(50),

    agent_url VARCHAR(512) NOT NULL,

    protocol_type VARCHAR(20) DEFAULT 'JSONRPC',

    streaming BOOLEAN DEFAULT FALSE,

    supported_interfaces JSONB,

    -- Source information
    source_type VARCHAR(20) NOT NULL,

    -- For URL mode:
    source_url VARCHAR(512),

    -- For Nacos mode:
    nacos_config_id VARCHAR(64),
    nacos_agent_name VARCHAR(255),

    -- Tenant isolation
    tenant_id VARCHAR(100) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100),

    raw_card JSONB,

    cached_at TIMESTAMP(6),
    cache_expires_at TIMESTAMP(6),

    is_available BOOLEAN DEFAULT TRUE,
    last_check_at TIMESTAMP(6),
    last_check_result VARCHAR(50),

    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_a2a_external_agent_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_external_agent_t IS 'External A2A agents discovered from URL or Nacos. Caches Agent Cards for A2A Client role.';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.id IS 'Primary key, auto-increment. Used as unique identifier for internal references.';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.name IS 'Agent name from Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.description IS 'Agent description from Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.version IS 'Agent version from Agent Card, e.g., 1.2.0';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.agent_url IS 'Primary A2A endpoint URL (http-json-rpc by default, extracted from supportedInterfaces)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.protocol_type IS 'Protocol type for calling this agent: JSONRPC, HTTP+JSON, or GRPC';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.streaming IS 'Whether this agent supports SSE streaming (from capabilities.streaming)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.supported_interfaces IS 'All supported interfaces array from Agent Card. Format: [{protocolBinding, url, protocolVersion}, ...]';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.source_type IS 'Discovery source: url or nacos';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.source_url IS 'Direct URL to agent card (for url source type)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.nacos_config_id IS 'Reference to Nacos config used for discovery (for nacos source type)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.nacos_agent_name IS 'Original name used for Nacos query';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.tenant_id IS 'Tenant ID for multi-tenancy isolation';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.created_by IS 'User who discovered this agent';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.updated_by IS 'User who last updated this record';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.raw_card IS 'Full original Agent Card JSON from discovery';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.cached_at IS 'Timestamp when Agent Card was cached';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.cache_expires_at IS 'Timestamp when cache expires';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.is_available IS 'Whether this agent is currently reachable';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.last_check_at IS 'Last health check timestamp';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.last_check_result IS 'Last health check result: OK, ERROR, TIMEOUT';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.create_time IS 'Record creation timestamp';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.update_time IS 'Record last update timestamp';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.delete_flag IS 'Soft delete flag: Y/N'; -- NOSONAR


CREATE TABLE IF NOT EXISTS nexent.ag_a2a_external_agent_relation_t (
    id BIGSERIAL PRIMARY KEY,
    local_agent_id INTEGER NOT NULL,
    external_agent_id BIGINT NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100),
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT uq_local_external_agent UNIQUE (local_agent_id, external_agent_id),
    CONSTRAINT fk_external_agent FOREIGN KEY (external_agent_id) REFERENCES nexent.ag_a2a_external_agent_t(id)
);

ALTER TABLE nexent.ag_a2a_external_agent_relation_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_external_agent_relation_t IS 'Relation between local agent and external A2A agent. Enables local agents to call external A2A agents as sub-agents.';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.id IS 'Primary key, auto-increment';  -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.local_agent_id IS 'Local parent agent ID (FK to ag_tenant_agent_t)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.external_agent_id IS 'External A2A agent ID (FK to ag_a2a_external_agent_t.id)';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.tenant_id IS 'Tenant ID for multi-tenancy isolation'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.is_enabled IS 'Whether this relation is active';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.created_by IS 'User who created this relation';
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.updated_by IS 'User who last updated this record'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.create_time IS 'Record creation timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.update_time IS 'Record last update timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_external_agent_relation_t.delete_flag IS 'Soft delete flag: Y/N';  -- NOSONAR

CREATE TABLE IF NOT EXISTS nexent.ag_a2a_server_agent_t (
    id BIGSERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    endpoint_id VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    version VARCHAR(50),
    agent_url VARCHAR(512),
    streaming BOOLEAN DEFAULT FALSE,
    supported_interfaces JSONB,
    card_overrides JSONB,
    is_enabled BOOLEAN DEFAULT FALSE,
    raw_card JSONB,
    published_at TIMESTAMP(6),
    unpublished_at TIMESTAMP(6),
    response_format VARCHAR(20) DEFAULT 'task',
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_a2a_server_agent_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_server_agent_t IS 'Local agents registered as A2A Server endpoints. Exposes Agent Cards for external A2A callers.';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.id IS 'Primary key, auto-increment';  -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.agent_id IS 'Local agent ID (FK to ag_tenant_agent_t)';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.user_id IS 'Owner user ID';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.tenant_id IS 'Tenant ID for multi-tenancy isolation'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.created_by IS 'User who created this A2A Server agent';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.updated_by IS 'User who last updated this A2A Server agent'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.endpoint_id IS 'Generated endpoint ID, format: a2a_{agent_id[:8]}_{hash[:8]}';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.name IS 'Agent name exposed in Agent Card (from agent or override)';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.description IS 'Agent description exposed in Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.version IS 'Agent version exposed in Agent Card';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.agent_url IS 'Primary A2A endpoint URL (http-json-rpc by default)';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.streaming IS 'Whether this agent supports SSE streaming';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.supported_interfaces IS 'All supported interfaces: [{protocolBinding, url, protocolVersion}, ...]';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.card_overrides IS 'User customizations for Agent Card (partial override)';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.is_enabled IS 'Whether A2A Server is enabled for this agent';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.raw_card IS 'Generated Agent Card JSON (for debugging)';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.published_at IS 'Timestamp when A2A Server was last enabled';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.unpublished_at IS 'Timestamp when A2A Server was disabled';
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.create_time IS 'Record creation timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.update_time IS 'Record last update timestamp'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.delete_flag IS 'Soft delete flag: Y/N'; -- NOSONAR
COMMENT ON COLUMN nexent.ag_a2a_server_agent_t.response_format IS 'Response format: ''task'' for full Task response, ''message'' for simple Message response';


CREATE TABLE IF NOT EXISTS nexent.ag_a2a_task_t (
    id VARCHAR(64) PRIMARY KEY,                      -- taskId
    context_id VARCHAR(64),                          -- contextId
    endpoint_id VARCHAR(64) NOT NULL,
    caller_user_id VARCHAR(100),
    caller_tenant_id VARCHAR(100),
    raw_request JSONB,
    task_state VARCHAR(50) NOT NULL DEFAULT 'TASK_STATE_SUBMITTED',
    state_timestamp TIMESTAMP(6),                    -- State update timestamp
    result_data JSONB,                              -- Final result (renamed from result to avoid SQL function conflict)
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP(6)
);

ALTER TABLE nexent.ag_a2a_task_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_task_t IS 'A2A tasks for tracking requests. Task is the unit of work, not all requests need to create a task.';
COMMENT ON COLUMN nexent.ag_a2a_task_t.id IS 'Task ID from A2A protocol, primary key';
COMMENT ON COLUMN nexent.ag_a2a_task_t.context_id IS 'Context ID for grouping related A2A tasks';
COMMENT ON COLUMN nexent.ag_a2a_task_t.endpoint_id IS 'Endpoint ID (FK to ag_a2a_server_agent_t.endpoint_id)';
COMMENT ON COLUMN nexent.ag_a2a_task_t.caller_user_id IS 'User ID of the caller (for audit)';
COMMENT ON COLUMN nexent.ag_a2a_task_t.caller_tenant_id IS 'Tenant ID of the caller (for audit)';
COMMENT ON COLUMN nexent.ag_a2a_task_t.raw_request IS 'Original A2A request payload';
COMMENT ON COLUMN nexent.ag_a2a_task_t.task_state IS 'Task state: TASK_STATE_SUBMITTED, TASK_STATE_WORKING, TASK_STATE_COMPLETED, TASK_STATE_FAILED, TASK_STATE_CANCELED, TASK_STATE_INPUT_REQUIRED, TASK_STATE_REJECTED, TASK_STATE_AUTH_REQUIRED';
COMMENT ON COLUMN nexent.ag_a2a_task_t.state_timestamp IS 'Task state last update timestamp';
COMMENT ON COLUMN nexent.ag_a2a_task_t.result_data IS 'Task final result data';
COMMENT ON COLUMN nexent.ag_a2a_task_t.create_time IS 'Task creation timestamp';
COMMENT ON COLUMN nexent.ag_a2a_task_t.update_time IS 'Task last update timestamp';
COMMENT ON COLUMN nexent.ag_a2a_task_t.completed_at IS 'Task completion timestamp';

CREATE TABLE IF NOT EXISTS nexent.ag_a2a_message_t (
    message_id VARCHAR(64) PRIMARY KEY,              -- messageId (A2A spec naming)
    task_id VARCHAR(64),                            -- taskId (associated task), can be NULL for simple requests
    message_index INTEGER NOT NULL,                  -- Sequence index
    role VARCHAR(20) NOT NULL CHECK (role IN ('ROLE_UNSPECIFIED', 'ROLE_USER', 'ROLE_AGENT')),  -- Following A2A spec: ROLE_UNSPECIFIED, ROLE_USER, ROLE_AGENT
    parts JSONB NOT NULL,                            -- Part array
    meta_data JSONB,                                  -- Optional metadata
    extensions JSONB,                               -- Extension URI list
    reference_task_ids JSONB,                        -- Referenced task IDs array
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, message_index)
);

ALTER TABLE nexent.ag_a2a_message_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_message_t IS 'A2A messages within tasks. Stores conversation history for multi-turn interactions.';
COMMENT ON COLUMN nexent.ag_a2a_message_t.message_id IS 'Message ID, primary key (A2A spec: messageId)';
COMMENT ON COLUMN nexent.ag_a2a_message_t.task_id IS 'Task ID this message belongs to (FK to ag_a2a_task_t.id), can be NULL for simple requests without Task';
COMMENT ON COLUMN nexent.ag_a2a_message_t.message_index IS 'Order of message in the conversation';
COMMENT ON COLUMN nexent.ag_a2a_message_t.role IS 'Message sender role: ROLE_UNSPECIFIED, ROLE_USER, or ROLE_AGENT';
COMMENT ON COLUMN nexent.ag_a2a_message_t.parts IS 'Message parts following A2A Part structure: [{"type": "text", "text": "..."}]';
COMMENT ON COLUMN nexent.ag_a2a_message_t.meta_data IS 'Optional message metadata';
COMMENT ON COLUMN nexent.ag_a2a_message_t.extensions IS 'Extension URI list';
COMMENT ON COLUMN nexent.ag_a2a_message_t.reference_task_ids IS 'Referenced task IDs array for multi-turn scenarios';
COMMENT ON COLUMN nexent.ag_a2a_message_t.create_time IS 'Message creation timestamp';

CREATE TABLE IF NOT EXISTS nexent.ag_a2a_artifact_t (
    id VARCHAR(64) PRIMARY KEY,                      -- Internal primary key
    artifact_id VARCHAR(64) NOT NULL,                 -- artifactId (A2A spec naming)
    task_id VARCHAR(64) NOT NULL,                    -- taskId (associated task, required)
    name VARCHAR(255),                               -- Human-readable name
    description TEXT,                               -- Description
    parts JSONB NOT NULL,                           -- Part array (following A2A spec)
    meta_data JSONB,                                -- Metadata
    extensions JSONB,                                -- Extension URI list
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_artifact_task FOREIGN KEY (task_id)
        REFERENCES nexent.ag_a2a_task_t(id) ON DELETE CASCADE,
    UNIQUE(task_id, artifact_id)
);

ALTER TABLE nexent.ag_a2a_artifact_t OWNER TO "root";

COMMENT ON TABLE nexent.ag_a2a_artifact_t IS 'A2A artifacts. Stores the output/artifacts produced by a task.';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.id IS 'Internal primary key';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.artifact_id IS 'Artifact ID (A2A spec: artifactId)';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.task_id IS 'Task ID this artifact belongs to (FK to ag_a2a_task_t.id), required - no standalone artifacts';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.name IS 'Human-readable artifact name';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.description IS 'Artifact description';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.parts IS 'Artifact parts following A2A Part structure: [{"type": "text", "text": "..."}]';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.meta_data IS 'Artifact metadata';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.extensions IS 'Extension URI list';
COMMENT ON COLUMN nexent.ag_a2a_artifact_t.create_time IS 'Artifact creation timestamp';
