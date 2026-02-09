from sqlalchemy import BigInteger, Boolean, Column, Integer, JSON, Numeric, PrimaryKeyConstraint, Sequence, String, Text, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func

SCHEMA = "nexent"

# Base class for tables without audit fields
class SimpleTableBase(DeclarativeBase):
    pass


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
    expected_chunk_size = Column(
        Integer, doc="Expected chunk size for embedding models, used during document chunking")
    maximum_chunk_size = Column(
        Integer, doc="Maximum chunk size for embedding models, used during document chunking")
    ssl_verify = Column(
        Boolean, default=True, doc="Whether to verify SSL certificates when connecting to this model API. Default is true. Set to false for local services without SSL support.")
    chunk_batch = Column(
        Integer, doc="Batch size for concurrent embedding requests during document chunking")


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

    agent_id = Column(Integer, Sequence(
        "ag_tenant_agent_t_agent_id_seq", schema=SCHEMA), nullable=False, primary_key=True, autoincrement=True, doc="ID")
    version_no = Column(Integer, default=0, nullable=False, primary_key=True, doc="Version number. 0 = draft/editing state, >=1 = published snapshot")
    name = Column(String(100), doc="Agent name")
    display_name = Column(String(100), doc="Agent display name")
    description = Column(Text, doc="Description")
    author = Column(String(100), doc="Agent author")
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
    business_logic_model_name = Column(String(100), doc="Model name used for business logic prompt generation")
    business_logic_model_id = Column(Integer, doc="Model ID used for business logic prompt generation, foreign key reference to model_record_t.model_id")
    group_ids = Column(String, doc="Agent group IDs list")
    is_new = Column(Boolean, default=False, doc="Whether this agent is marked as new for the user")
    current_version_no = Column(Integer, nullable=True, doc="Current published version number. NULL means no version published yet")


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
    version_no = Column(Integer, default=0, nullable=False, doc="Version number. 0 = draft/editing state, >=1 = published snapshot")


class KnowledgeRecord(TableBase):
    """
    Records the description and status information of knowledge bases
    """
    __tablename__ = "knowledge_record_t"
    __table_args__ = {"schema": "nexent"}

    knowledge_id = Column(BigInteger, Sequence("knowledge_record_t_knowledge_id_seq", schema="nexent"),
                          primary_key=True, nullable=False, doc="Knowledge base ID, unique primary key")
    index_name = Column(String(100), doc="Internal Elasticsearch index name")
    knowledge_name = Column(String(100), doc="User-facing knowledge base name")
    knowledge_describe = Column(String(3000), doc="Knowledge base description")
    knowledge_sources = Column(String(300), doc="Knowledge base sources")
    embedding_model_name = Column(String(200), doc="Embedding model name, used to record the embedding model used by the knowledge base")
    tenant_id = Column(String(100), doc="Tenant ID")
    group_ids = Column(String, doc="Knowledge base group IDs list")
    ingroup_permission = Column(
        String(30), doc="In-group permission: EDIT, READ_ONLY, PRIVATE")


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
    config_value = Column(Text, doc="the value of the config")


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
    status = Column(
        Boolean,
        default=None,
        doc="MCP server connection status, True=connected, False=disconnected, None=unknown",
    )
    container_id = Column(
        String(200),
        doc="Docker container ID for MCP service, None for non-containerized MCP",
    )


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
    user_role = Column(String(30), doc="User role: SUPER_ADMIN, ADMIN, DEV, USER")
    user_email = Column(String(255), doc="User email address")


class AgentRelation(TableBase):
    """
    Agent parent-child relationship table
    """
    __tablename__ = "ag_agent_relation_t"
    __table_args__ = {"schema": SCHEMA}

    relation_id = Column(Integer, primary_key=True, autoincrement=True, nullable=False, doc="Relationship ID, primary key")
    selected_agent_id = Column(Integer, primary_key=True, doc="Selected agent ID")
    parent_agent_id = Column(Integer, doc="Parent agent ID")
    tenant_id = Column(String(100), doc="Tenant ID")
    version_no = Column(Integer, default=0, nullable=False, doc="Version number. 0 = draft/editing state, >=1 = published snapshot")


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


class TenantInvitationCode(TableBase):
    """
    Tenant invitation code information table
    """
    __tablename__ = "tenant_invitation_code_t"
    __table_args__ = {"schema": SCHEMA}

    invitation_id = Column(Integer, Sequence("tenant_invitation_code_t_invitation_id_seq", schema=SCHEMA),
                           primary_key=True, nullable=False, doc="Invitation ID, primary key")
    tenant_id = Column(String(100), nullable=False,
                       doc="Tenant ID, foreign key")
    invitation_code = Column(String(100), nullable=False,
                             unique=True, doc="Invitation code")
    group_ids = Column(String, doc="Associated group IDs list")
    capacity = Column(Integer, nullable=False, default=1,
                      doc="Invitation code capacity")
    expiry_date = Column(TIMESTAMP(timezone=False),
                         doc="Invitation code expiry date")
    status = Column(String(30), nullable=False,
                    doc="Invitation code status: IN_USE, EXPIRE, DISABLE, RUN_OUT")
    code_type = Column(String(30), nullable=False,
                       doc="Invitation code type: ADMIN_INVITE, DEV_INVITE, USER_INVITE")


class TenantInvitationRecord(TableBase):
    """
    Tenant invitation record table
    """
    __tablename__ = "tenant_invitation_record_t"
    __table_args__ = {"schema": SCHEMA}

    invitation_record_id = Column(Integer, Sequence("tenant_invitation_record_t_invitation_record_id_seq", schema=SCHEMA),
                                  primary_key=True, nullable=False, doc="Invitation record ID, primary key")
    invitation_id = Column(Integer, nullable=False,
                           doc="Invitation ID, foreign key")
    user_id = Column(String(100), nullable=False, doc="User ID")


class TenantGroupInfo(TableBase):
    """
    Tenant group information table
    """
    __tablename__ = "tenant_group_info_t"
    __table_args__ = {"schema": SCHEMA}

    group_id = Column(Integer, Sequence("tenant_group_info_t_group_id_seq", schema=SCHEMA),
                      primary_key=True, nullable=False, doc="Group ID, primary key")
    tenant_id = Column(String(100), nullable=False,
                       doc="Tenant ID, foreign key")
    group_name = Column(String(100), nullable=False, doc="Group name")
    group_description = Column(String(500), doc="Group description")


class TenantGroupUser(TableBase):
    """
    Tenant group user membership table
    """
    __tablename__ = "tenant_group_user_t"
    __table_args__ = {"schema": SCHEMA}

    group_user_id = Column(Integer, Sequence("tenant_group_user_t_group_user_id_seq", schema=SCHEMA),
                           primary_key=True, nullable=False, doc="Group user ID, primary key")
    group_id = Column(Integer, nullable=False, doc="Group ID, foreign key")
    user_id = Column(String(100), nullable=False, doc="User ID, foreign key")


class RolePermission(SimpleTableBase):
    """
    Role permission configuration table
    Note: This table does not have audit fields (create_time, update_time, etc.)
    """
    __tablename__ = "role_permission_t"
    __table_args__ = {"schema": SCHEMA}

    role_permission_id = Column(Integer, Sequence("role_permission_t_role_permission_id_seq", schema=SCHEMA),
                                primary_key=True, nullable=False, doc="Role permission ID, primary key")
    user_role = Column(String(30), nullable=False,
                       doc="User role: SU, ADMIN, DEV, USER")
    permission_category = Column(String(30), doc="Permission category")
    permission_type = Column(String(30), doc="Permission type")
    permission_subtype = Column(String(30), doc="Permission subtype")


class AgentVersion(TableBase):
    """
    Agent version metadata table. Stores version info, release notes, and version lineage.
    """
    __tablename__ = "ag_tenant_agent_version_t"
    __table_args__ = {"schema": SCHEMA}

    id = Column(BigInteger, Sequence("ag_tenant_agent_version_t_id_seq", schema=SCHEMA),
                primary_key=True, nullable=False, doc="Primary key, auto-increment")
    tenant_id = Column(String(100), nullable=False, doc="Tenant ID")
    agent_id = Column(Integer, nullable=False, doc="Agent ID")
    version_no = Column(Integer, nullable=False, doc="Version number, starts from 1. Does not include 0 (draft)")
    version_name = Column(String(100), doc="User-defined version name for display")
    release_note = Column(Text, doc="Release notes / publish remarks")
    source_version_no = Column(Integer, doc="Source version number. If this version is a rollback, record the source version")
    source_type = Column(String(30), doc="Source type: NORMAL (normal publish) / ROLLBACK (rollback and republish)")
    status = Column(String(30), default="RELEASED", doc="Version status: RELEASED / DISABLED / ARCHIVED")
