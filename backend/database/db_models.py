from sqlalchemy import Boolean, Column, Integer, JSON, Numeric, Sequence, String, Text, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func

SCHEMA = "nexent"


class TableBase(DeclarativeBase):
    create_time = Column(TIMESTAMP(timezone=False),
                         server_default=func.now(), doc="Creation time")
    update_time = Column(TIMESTAMP(timezone=False), server_default=func.now(
    ), onupdate=func.now(), doc="Update time")
    created_by = Column(String(100), doc="Creator")
    updated_by = Column(String(100), doc="Updater")
    delete_flag = Column(String(1), default="N",
                         doc="Whether it is deleted. Optional values: Y/N")
    pass


class ConversationRecord(TableBase):
    """
    Overall information table for Q&A conversations
    """
    __tablename__ = "conversation_record_t"
    __table_args__ = {"schema": SCHEMA}

    conversation_id = Column(Integer, Sequence(
        "conversation_record_t_conversation_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    conversation_title = Column(String(100), doc="Conversation title")


class ConversationMessage(TableBase):
    """
    Holds the specific response message content in the conversation
    """
    __tablename__ = "conversation_message_t"
    __table_args__ = {"schema": SCHEMA}

    message_id = Column(Integer, Sequence(
        "conversation_message_t_message_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    conversation_id = Column(
        Integer, doc="Formal foreign key used to associate with the conversation")
    message_index = Column(
        Integer, doc="Sequence number for frontend display sorting")
    message_role = Column(
        String(30), doc="The role sending the message, such as system, assistant, user")
    message_content = Column(String, doc="The complete content of the message")
    minio_files = Column(
        String, doc="Images or documents uploaded by the user on the chat page, stored as a list")
    opinion_flag = Column(String(
        1), doc="User evaluation of the conversation. Enumeration value \"Y\" represents a positive review, \"N\" represents a negative review")


class ConversationMessageUnit(TableBase):
    """
    Holds the agent's output content in each message
    """
    __tablename__ = "conversation_message_unit_t"
    __table_args__ = {"schema": SCHEMA}

    unit_id = Column(Integer, Sequence("conversation_message_unit_t_unit_id_seq",
                     schema=SCHEMA), primary_key=True, nullable=False)
    message_id = Column(
        Integer, doc="Formal foreign key used to associate with the message")
    conversation_id = Column(
        Integer, doc="Formal foreign key used to associate with the conversation")
    unit_index = Column(
        Integer, doc="Sequence number for frontend display sorting")
    unit_type = Column(String(100), doc="Type of the smallest answer unit")
    unit_content = Column(
        String, doc="Complete content of the smallest reply unit")


class ConversationSourceImage(TableBase):
    """
    Holds the search image source information of conversation messages
    """
    __tablename__ = "conversation_source_image_t"
    __table_args__ = {"schema": SCHEMA}

    image_id = Column(Integer, Sequence(
        "conversation_source_image_t_image_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    conversation_id = Column(
        Integer, doc="Formal foreign key used to associate with the conversation to which the search source belongs")
    message_id = Column(
        Integer, doc="Formal foreign key used to associate with the conversation message to which the search source belongs")
    unit_id = Column(
        Integer, doc="Formal foreign key used to associate with the smallest message unit (if any) to which the search source belongs")
    image_url = Column(String, doc="URL address of the image")
    cite_index = Column(
        Integer, doc="[Reserved] Citation serial number for precise traceability")
    search_type = Column(String(
        100), doc="[Reserved] Search source type, used to distinguish the retrieval tool from which the record originates. Optional values: web/local")


class ConversationSourceSearch(TableBase):
    """
    Holds the search text source information referenced by the response messages in the conversation
    """
    __tablename__ = "conversation_source_search_t"
    __table_args__ = {"schema": SCHEMA}

    search_id = Column(Integer, Sequence(
        "conversation_source_search_t_search_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    unit_id = Column(
        Integer, doc="Formal foreign key used to associate with the smallest message unit (if any) to which the search source belongs")
    message_id = Column(
        Integer, doc="Formal foreign key used to associate with the conversation message to which the search source belongs")
    conversation_id = Column(
        Integer, doc="Formal foreign key used to associate with the conversation to which the search source belongs")
    source_type = Column(String(
        100), doc="Source type, used to distinguish whether source_location is a URL or a path. Optional values: url/text")
    source_title = Column(
        String(400), doc="Title or file name of the search source")
    source_location = Column(
        String(400), doc="URL link or file path of the search source")
    source_content = Column(String, doc="Original text of the search source")
    score_overall = Column(Numeric(
        7, 6), doc="Overall similarity score between the source and the user query, calculated by weighted average of details")
    score_accuracy = Column(Numeric(7, 6), doc="Accuracy score")
    score_semantic = Column(Numeric(7, 6), doc="Semantic similarity score")
    published_date = Column(TIMESTAMP(
        timezone=False), doc="Upload date of local files or network search date")
    cite_index = Column(
        Integer, doc="Citation serial number for precise traceability")
    search_type = Column(String(
        100), doc="Search source type, specifically describing the retrieval tool used for this search record. Optional values: web_search/knowledge_base_search")
    tool_sign = Column(String(
        30), doc="Simple tool identifier used to distinguish the index source in the summary text output by the large model")


class ModelRecord(TableBase):
    """
    Model list defined by the user on the configuration page
    """
    __tablename__ = "model_record_t"
    __table_args__ = {"schema": SCHEMA}

    model_id = Column(Integer, Sequence("model_record_t_model_id_seq", schema=SCHEMA),
                      primary_key=True, nullable=False, doc="Model ID, unique primary key")
    model_repo = Column(String(100), doc="Model path address")
    model_name = Column(String(100), nullable=False, doc="Model name")
    model_factory = Column(String(
        100), doc="Model vendor, determining the API key and the specific format of the model response. Currently defaults to OpenAI-API-Compatible.")
    model_type = Column(
        String(100), doc="Model type, such as chat, embedding, rerank, tts, asr")
    api_key = Column(
        String(500), doc="Model API key, used for authentication for some models")
    base_url = Column(
        String(500), doc="Base URL address for requesting remote model services")
    max_tokens = Column(Integer, doc="Maximum available tokens of the model")
    used_token = Column(
        Integer, doc="Number of tokens already used by the model in Q&A")
    display_name = Column(String(
        100), doc="Model name directly displayed on the frontend, customized by the user")
    connect_status = Column(String(
        100), doc="Model connectivity status of the latest detection. Optional values: Detecting, Available, Unavailable")
    tenant_id = Column(String(100), doc="Tenant ID for filtering")


class ToolInfo(TableBase):
    """
    Information table for prompt tools
    """
    __tablename__ = "ag_tool_info_t"
    __table_args__ = {"schema": SCHEMA}

    tool_id = Column(Integer, primary_key=True, nullable=False, doc="ID")
    name = Column(String(100), doc="Unique key name")
    origin_name = Column(String(100), doc="Original name")
    class_name = Column(
        String(100), doc="Tool class name, used when the tool is instantiated")
    description = Column(String(2048), doc="Prompt tool description")
    source = Column(String(100), doc="Source")
    author = Column(String(100), doc="Tool author")
    usage = Column(String(100), doc="Usage")
    params = Column(JSON, doc="Tool parameter information (json)")
    inputs = Column(String(2048), doc="Prompt tool inputs description")
    output_type = Column(String(100), doc="Prompt tool output description")
    category = Column(String(100), doc="Tool category description")
    is_available = Column(
        Boolean, doc="Whether the tool can be used under the current main service")


class AgentInfo(TableBase):
    """
    Information table for agents
    """
    __tablename__ = "ag_tenant_agent_t"
    __table_args__ = {"schema": SCHEMA}

    agent_id = Column(Integer, primary_key=True, nullable=False, doc="ID")
    name = Column(String(100), doc="Agent name")
    display_name = Column(String(100), doc="Agent display name")
    description = Column(Text, doc="Description")
    model_name = Column(String(100), doc="[DEPRECATED] Name of the model used, use model_id instead")
    model_id = Column(Integer, doc="Model ID, foreign key reference to model_record_t.model_id")
    max_steps = Column(Integer, doc="Maximum number of steps")
    duty_prompt = Column(Text, doc="Duty prompt content")
    constraint_prompt = Column(Text, doc="Constraint prompt content")
    few_shots_prompt = Column(Text, doc="Few shots prompt content")
    parent_agent_id = Column(Integer, doc="Parent Agent ID")
    tenant_id = Column(String(100), doc="Belonging tenant")
    enabled = Column(Boolean, doc="Enabled")
    provide_run_summary = Column(
        Boolean, doc="Whether to provide the running summary to the manager agent")
    business_description = Column(
        Text, doc="Manually entered by the user to describe the entire business process")


class ToolInstance(TableBase):
    """
    Information table for tenant tool configuration.
    """
    __tablename__ = "ag_tool_instance_t"
    __table_args__ = {"schema": SCHEMA}

    tool_instance_id = Column(
        Integer, primary_key=True, nullable=False, doc="ID")
    tool_id = Column(Integer, doc="Tenant tool ID")
    agent_id = Column(Integer, doc="Agent ID")
    params = Column(JSON, doc="Parameter configuration")
    user_id = Column(String(100), doc="User ID")
    tenant_id = Column(String(100), doc="Tenant ID")
    enabled = Column(Boolean, doc="Enabled")


class KnowledgeRecord(TableBase):
    """
    Records the description and status information of knowledge bases
    """
    __tablename__ = "knowledge_record_t"
    __table_args__ = {"schema": "nexent"}

    knowledge_id = Column(Integer, Sequence("knowledge_record_t_knowledge_id_seq", schema="nexent"),
                          primary_key=True, nullable=False, doc="Knowledge base ID, unique primary key")
    index_name = Column(String(100), doc="Knowledge base name")
    knowledge_describe = Column(String(3000), doc="Knowledge base description")
    knowledge_sources = Column(String(300), doc="Knowledge base sources")
    embedding_model_name = Column(String(200), doc="Embedding model name, used to record the embedding model used by the knowledge base")
    tenant_id = Column(String(100), doc="Tenant ID")


class TenantConfig(TableBase):
    """
    Tenant configuration information table
    """
    __tablename__ = "tenant_config_t"
    __table_args__ = {"schema": SCHEMA}

    tenant_config_id = Column(Integer, Sequence(
        "tenant_config_t_tenant_config_id_seq", schema=SCHEMA), primary_key=True, nullable=False, doc="ID")
    tenant_id = Column(String(100), doc="Tenant ID")
    user_id = Column(String(100), doc="User ID")
    value_type = Column(String(
        100), doc=" the data type of config_value, optional values: single/multi", default="single")
    config_key = Column(String(100), doc="the key of the config")
    config_value = Column(String(10000), doc="the value of the config")


class MemoryUserConfig(TableBase):
    """
    Tenant configuration information table
    """
    __tablename__ = "memory_user_config_t"
    __table_args__ = {"schema": SCHEMA}

    config_id = Column(Integer, Sequence("memory_user_config_t_config_id_seq",
                       schema=SCHEMA), primary_key=True, nullable=False, doc="ID")
    tenant_id = Column(String(100), doc="Tenant ID")
    user_id = Column(String(100), doc="User ID")
    value_type = Column(String(
        100), doc=" the data type of config_value, optional values: single/multi", default="single")
    config_key = Column(String(100), doc="the key of the config")
    config_value = Column(String(10000), doc="the value of the config")


class McpRecord(TableBase):
    """
    MCP (Model Context Protocol) records table
    """
    __tablename__ = "mcp_record_t"
    __table_args__ = {"schema": SCHEMA}

    mcp_id = Column(Integer, Sequence("mcp_record_t_mcp_id_seq", schema=SCHEMA),
                    primary_key=True, nullable=False, doc="MCP record ID, unique primary key")
    tenant_id = Column(String(100), doc="Tenant ID")
    user_id = Column(String(100), doc="User ID")
    mcp_name = Column(String(100), doc="MCP name")
    mcp_server = Column(String(500), doc="MCP server address")
    status = Column(Boolean, default=None,
                    doc="MCP server connection status, True=connected, False=disconnected, None=unknown")


class UserTenant(TableBase):
    """
    User and tenant relationship table
    """
    __tablename__ = "user_tenant_t"
    __table_args__ = {"schema": SCHEMA}

    user_tenant_id = Column(Integer, Sequence("user_tenant_t_user_tenant_id_seq", schema=SCHEMA),
                            primary_key=True, nullable=False, doc="User tenant relationship ID, unique primary key")
    user_id = Column(String(100), nullable=False, doc="User ID")
    tenant_id = Column(String(100), nullable=False, doc="Tenant ID")


class AgentRelation(TableBase):
    """
    Agent parent-child relationship table
    """
    __tablename__ = "ag_agent_relation_t"
    __table_args__ = {"schema": SCHEMA}

    relation_id = Column(Integer, primary_key=True,
                         nullable=False, doc="Relationship ID, primary key")
    selected_agent_id = Column(Integer, doc="Selected agent ID")
    parent_agent_id = Column(Integer, doc="Parent agent ID")
    tenant_id = Column(String(100), doc="Tenant ID")


class PartnerMappingId(TableBase):
    """
    External-Internal ID mapping table for partners
    """
    __tablename__ = "partner_mapping_id_t"
    __table_args__ = {"schema": SCHEMA}

    mapping_id = Column(Integer, Sequence("partner_mapping_id_t_mapping_id_seq",
                        schema=SCHEMA), primary_key=True, nullable=False, doc="ID")
    external_id = Column(
        String(100), doc="The external id given by the outer partner")
    internal_id = Column(
        Integer, doc="The internal id of the other database table")
    mapping_type = Column(String(
        30), doc="Type of the external - internal mapping, value set: CONVERSATION")
    tenant_id = Column(String(100), doc="Tenant ID")
    user_id = Column(String(100), doc="User ID")
