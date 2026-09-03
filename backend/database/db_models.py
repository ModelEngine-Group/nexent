from sqlalchemy import (
    JSON,
    TIMESTAMP,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


# Standard protocol labels used across A2A models
PROTOCOL_HTTP_JSON = "HTTP+JSON"
PROTOCOL_JSONRPC = "JSONRPC"
PROTOCOL_GRPC = "GRPC"

SCHEMA = "nexent"

# Shared doc strings for primary key columns
_PRIMARY_KEY_DOC = "Primary key, auto-increment"
_TENANT_ID_DOC = "Tenant ID for multi-tenancy isolation"
_PUBLISHER_TENANT_ID_DOC = "Publisher tenant ID"
_PUBLISHER_USER_ID_DOC = "Publisher user ID"
_MCP_NAME_DOC = "MCP name"
_INGROUP_PERMISSION_DOC = "In-group permission: EDIT, READ_ONLY, PRIVATE"

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
    agent_id = Column(Integer, doc="Agent ID used by the latest run in this conversation")
    chat_mode = Column(
        String(16),
        nullable=False,
        server_default=text("'execution'"),
        doc="UI chat mode for the conversation: 'planning' or 'execution'",
    )
    knowledge_scope = Column(
        JSONB,
        nullable=True,
        doc="Conversation-scoped desired policy for local and AIDP knowledge retrieval",
    )
    runtime_metadata = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        doc="Conversation-scoped runtime metadata available to agent runs",
    )
    runtime_metadata_version = Column(
        Integer,
        nullable=False,
        server_default=text("0"),
        doc="Monotonic version of conversation runtime metadata",
    )


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
    status = Column(
        String(30), default='completed',
        doc="Lifecycle status: pending / streaming / completed / failed / stopped")


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
    unit_status = Column(
        String(30), default='completed',
        doc="Lifecycle status: streaming (still aggregating) or completed (fully persisted)")
    tool_call_id = Column(
        String(36), doc="Unique ID of the originating tool invocation. Used to attribute side-channel units to the correct tool call when multiple calls run in parallel.")
    invocation_id = Column(
        String(36), doc="Identifies which sub-agent invocation produced this unit. Used by the frontend history adapter to route deep-thinking / reasoning chunks into the correct nested sub-agent card.")


class AgentAutomationTask(TableBase):
    """User-managed scheduled automation task bound to one conversation."""

    __tablename__ = "agent_automation_task_t"
    __table_args__ = (
        Index(
            "idx_agent_automation_due",
            "status",
            "next_fire_at",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "idx_agent_automation_owner",
            "tenant_id",
            "user_id",
            "status",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "uq_agent_automation_conversation_active",
            "conversation_id",
            unique=True,
            postgresql_where=text("delete_flag = 'N' AND status <> 'DELETED'"),
        ),
        {"schema": SCHEMA},
    )

    task_id = Column(BigInteger, Sequence(
        "agent_automation_task_t_task_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, doc="Tenant ID")
    user_id = Column(String(100), nullable=False, doc="Owner user ID")
    conversation_id = Column(BigInteger, nullable=False, doc="Bound conversation ID")
    agent_id = Column(BigInteger, nullable=False, doc="Bound agent ID")
    agent_version_no = Column(Integer, nullable=True, doc="Pinned agent version")
    title = Column(String(255), nullable=False, doc="Task title")
    instruction = Column(Text, nullable=False, doc="Base instruction for every automation run")
    status = Column(String(32), nullable=False, doc="Task lifecycle status")
    source = Column(String(32), nullable=False, doc="Creation source")
    schedule_mode = Column(String(16), nullable=False, doc="ONCE or RECURRING")
    schedule_rule_type = Column(String(16), nullable=False, doc="AT, INTERVAL, or CRON")
    schedule_expr = Column(Text, nullable=True, doc="Display schedule expression")
    schedule_config = Column(JSONB, nullable=False, doc="Normalized ScheduleTrigger payload")
    capability_requirements = Column(JSONB, doc="Capability requirements parsed from user intent")
    capability_bindings = Column(JSONB, doc="Confirmed matched capabilities")
    runtime_snapshot = Column(JSONB, doc="Agent/runtime capability snapshot at creation time")
    timezone = Column(String(64), nullable=False, doc="IANA timezone")
    next_fire_at = Column(TIMESTAMP(timezone=True), nullable=True, doc="Next scheduled fire time")
    last_fire_at = Column(TIMESTAMP(timezone=True), nullable=True, doc="Last scheduled fire time")
    fire_count = Column(Integer, default=0, nullable=False, doc="Number of scheduled fires")
    last_run_status = Column(String(32), nullable=True, doc="Latest run status")
    last_error = Column(Text, nullable=True, doc="Latest run error")
    consecutive_failures = Column(Integer, default=0, nullable=False, doc="Consecutive failure count")
    timeout_seconds = Column(Integer, nullable=False, doc="Single-run timeout")
    overlap_policy = Column(String(16), nullable=False, doc="Overlap policy")
    misfire_policy = Column(String(16), nullable=False, doc="Misfire policy")
    lock_owner = Column(String(128), nullable=True, doc="Scheduler lease owner")
    lock_until = Column(TIMESTAMP(timezone=True), nullable=True, doc="Scheduler lease expiry")


class AgentAutomationRun(TableBase):
    """Execution history for an automation task fire."""

    __tablename__ = "agent_automation_run_t"
    __table_args__ = (
        Index(
            "idx_agent_automation_run_task",
            "task_id",
            "scheduled_fire_at",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "idx_agent_automation_run_conversation",
            "conversation_id",
            "status",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "uq_agent_automation_active_occurrence",
            "task_id",
            "scheduled_fire_at",
            unique=True,
            postgresql_where=text(
                "delete_flag = 'N' AND trigger_type = 'SCHEDULED' "
                "AND status IN ('QUEUED', 'RUNNING')"
            ),
        ),
        {"schema": SCHEMA},
    )

    run_id = Column(BigInteger, Sequence(
        "agent_automation_run_t_run_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    task_id = Column(BigInteger, nullable=False, doc="Automation task ID")
    tenant_id = Column(String(100), nullable=False, doc="Tenant ID")
    user_id = Column(String(100), nullable=False, doc="Owner user ID")
    conversation_id = Column(BigInteger, nullable=False, doc="Bound conversation ID")
    scheduled_fire_at = Column(TIMESTAMP(timezone=True), nullable=False, doc="Scheduled fire time")
    actual_fire_at = Column(TIMESTAMP(timezone=True), nullable=True, doc="Actual fire time")
    trigger_type = Column(String(32), nullable=False, doc="SCHEDULED or MANUAL")
    status = Column(String(32), nullable=False, doc="Run lifecycle status")
    generated_prompt = Column(Text, nullable=True, doc="Prompt appended to the conversation")
    user_message_id = Column(BigInteger, nullable=True, doc="Automation user message ID")
    assistant_message_id = Column(BigInteger, nullable=True, doc="Assistant message ID")
    started_at = Column(TIMESTAMP(timezone=True), nullable=True, doc="Run start time")
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True, doc="Run finish time")
    duration_ms = Column(BigInteger, nullable=True, doc="Run duration in milliseconds")
    error_code = Column(String(64), nullable=True, doc="Automation error code")
    error_message = Column(Text, nullable=True, doc="Automation error message")


class AgentAutomationProposal(TableBase):
    """Pending automation task proposal created from chat intent."""

    __tablename__ = "agent_automation_proposal_t"
    __table_args__ = (
        Index(
            "idx_agent_automation_proposal_owner",
            "tenant_id",
            "user_id",
            "status",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "uq_agent_automation_proposal_source_message",
            "tenant_id",
            "user_id",
            "source_message_id",
            unique=True,
            postgresql_where=text("delete_flag = 'N' AND source_message_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    proposal_id = Column(BigInteger, Sequence(
        "agent_automation_proposal_t_proposal_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, doc="Tenant ID")
    user_id = Column(String(100), nullable=False, doc="Owner user ID")
    conversation_id = Column(BigInteger, nullable=False, doc="Source conversation ID")
    agent_id = Column(BigInteger, nullable=False, doc="Bound agent ID")
    source_message_id = Column(BigInteger, nullable=True, doc="User message that requested the proposal")
    proposed_task = Column(JSONB, nullable=False, doc="Proposed automation task payload")
    capability_resolution = Column(JSONB, nullable=False, doc="Capability matching result")
    status = Column(String(32), nullable=False, doc="PENDING, ACCEPTED, REJECTED, or EXPIRED")
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False, doc="Proposal expiry time")


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


class ConversationShare(TableBase):
    """
    Public read-only snapshot of selected Q&A pairs from a conversation.
    """
    __tablename__ = "conversation_share_t"
    __table_args__ = (
        Index("idx_conversation_share_token", "share_token"),
        Index("idx_conversation_share_conversation_id", "conversation_id"),
        {"schema": SCHEMA},
    )

    share_id = Column(Integer, Sequence(
        "conversation_share_t_share_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    share_token = Column(String(64), nullable=False, unique=True,
                         doc="Opaque public share token")
    conversation_id = Column(Integer, nullable=False,
                             doc="Original conversation ID")
    tenant_id = Column(String(100), doc="Tenant that created the share")
    title = Column(String(200), doc="Snapshot title")
    mode = Column(String(30), default="selected",
                  doc="Share mode: all or selected")
    selected_message_ids = Column(JSONB, doc="Selected original message IDs")
    snapshot_json = Column(JSONB, nullable=False,
                           doc="Frozen frontend-compatible conversation payload")
    status = Column(String(30), default="active",
                    doc="active or revoked")
    expire_time = Column(TIMESTAMP(timezone=False),
                         doc="Optional expiration time")


class ConversationShareAsset(TableBase):
    """
    File objects allowed to be accessed through a public share token.
    """
    __tablename__ = "conversation_share_asset_t"
    __table_args__ = (
        Index("idx_conversation_share_asset_token", "share_token"),
        Index("idx_conversation_share_asset_id", "asset_id"),
        {"schema": SCHEMA},
    )

    share_asset_id = Column(Integer, Sequence(
        "conversation_share_asset_t_share_asset_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    asset_id = Column(String(64), nullable=False, unique=True,
                      doc="Opaque public asset token")
    share_token = Column(String(64), nullable=False,
                         doc="Parent share token")
    object_name = Column(String(1000), nullable=False,
                         doc="Original MinIO object name")
    filename = Column(String(500), doc="Display/download filename")
    content_type = Column(String(200), doc="Content type")
    size = Column(BigInteger, doc="File size in bytes")
    source_kind = Column(String(50), doc="attachment, source, image, markdown")
    metadata_json = Column(JSONB, doc="Original reference metadata")


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
    model_appid = Column(
        String(100), doc="Application ID for model authentication (used by some STT/TTS providers like Volcano Engine)")
    access_token = Column(
        String(100), doc="Access token for model authentication (used by some STT/TTS providers like Volcano Engine)")
    timeout_seconds = Column(
        Integer, doc="Request timeout in seconds for this model. Default is 120 seconds.")
    concurrency_limit = Column(
        Integer, doc="Maximum concurrent requests for this model. Default is null (unlimited).")
    context_window_tokens = Column(
        Integer, doc="Total combined input/output context window in tokens, when the provider uses a combined window. Nullable.")
    max_input_tokens = Column(
        Integer, doc="Provider hard input-token limit when distinct from the combined window. Nullable.")
    max_output_tokens = Column(
        Integer, doc="Provider-supported or operator-configured completion-output cap. Replaces the ambiguous LLM meaning of max_tokens. Nullable.")
    default_output_reserve_tokens = Column(
        Integer, doc="Default output allowance reserved per request before constructing input context. Nullable.")
    tokenizer_family = Column(
        String(100), doc="Token-counting strategy or provider/model tokenizer identifier mapped via tokenizer_registry. Nullable.")
    capacity_source = Column(
        String(100), doc="Source of the persisted capacity value. Optional values: operator, profile, provider_candidate, legacy, default, unknown.")
    capability_profile_version = Column(
        String(100), doc="Version of the approved provider/model capability profile used by the request, e.g. openai/gpt-4o@1.")


class ModelMonitoringRecord(SimpleTableBase):
    """
    Model monitoring record table - stores per-request LLM performance metrics.
    Uses SimpleTableBase to avoid audit fields (created_by, updated_by, etc.).
    """

    __tablename__ = "model_monitoring_record_t"
    __table_args__ = (
        Index("ix_monitoring_model_id", "model_id"),
        Index("ix_monitoring_tenant_id", "tenant_id"),
        Index("ix_monitoring_agent_id", "agent_id"),
        Index("ix_monitoring_create_time", "create_time"),
        Index("ix_monitoring_is_error", "is_error"),
        Index("ix_monitoring_model_time", "model_id", "create_time"),
        Index("ix_monitoring_model_type", "model_type"),
        {"schema": SCHEMA},
    )

    monitoring_id = Column(
        Integer,
        Sequence("model_monitoring_record_t_monitoring_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="Monitoring record ID, auto-increment primary key",
    )
    model_id = Column(
        Integer, doc="Model ID, foreign key reference to model_record_t.model_id"
    )
    model_name = Column(
        String(100), nullable=False, doc="Model name at the time of the request"
    )
    agent_id = Column(Integer, doc="Agent ID that initiated the request")
    agent_name = Column(
        String(100), doc="Agent name at the time of the request")
    conversation_id = Column(
        Integer, doc="Conversation ID associated with this request"
    )
    tenant_id = Column(
        String(100), nullable=False, doc="Tenant ID for multi-tenant isolation"
    )
    user_id = Column(String(100), doc="User ID who initiated the request")
    request_duration_ms = Column(
        Integer, doc="Total request duration in milliseconds")
    ttft_ms = Column(Integer, doc="Time to first token in milliseconds")
    input_tokens = Column(Integer, doc="Number of input tokens")
    output_tokens = Column(Integer, doc="Number of output tokens")
    total_tokens = Column(Integer, doc="Total tokens (input + output)")
    context_window_tokens = Column(
        Integer, doc="Resolved total combined model context window for this request"
    )
    default_output_reserve_tokens = Column(
        Integer, doc="Default output allowance reserved before input context construction"
    )
    capability_profile_version = Column(
        String(100), doc="Version of the resolved capacity profile for this request"
    )
    capacity_source = Column(
        String(100), doc="Dominant source of resolved capacity fields for this request"
    )
    requested_output_tokens = Column(
        Integer, doc="Output tokens requested or reserved during capacity resolution"
    )
    provider_input_limit_tokens = Column(
        Integer, doc="Resolved provider input-token limit used by context management"
    )
    tokenizer_family = Column(
        String(100), doc="Tokenizer family used for request token counting"
    )
    counting_mode = Column(
        String(20), doc="Token counting mode for the request: exact or estimated"
    )
    unknown_capabilities = Column(
        JSONB, doc="Structured list of capacity capabilities unknown at resolution time"
    )
    capacity_fingerprint = Column(
        String(64), doc="Fingerprint of the resolved model capacity snapshot"
    )
    budget_fingerprint = Column(
        String(64), doc="Fingerprint of the resolved W2 safe input budget snapshot"
    )
    budget_w1_fingerprint = Column(
        String(64), doc="W1 capacity fingerprint consumed by the W2 budget snapshot"
    )
    budget_requested_output_tokens = Column(
        Integer, doc="W2 trusted requested output tokens used at dispatch"
    )
    budget_output_reserve_source = Column(
        String(32), doc="Source of the W2 requested output token reserve"
    )
    budget_provider_input_limit_tokens = Column(
        Integer, doc="Provider input limit after applying the W2 output reserve"
    )
    budget_uncertainty_reserve_tokens = Column(
        Integer, doc="Additional W2 uncertainty reserve deducted from input budget"
    )
    budget_uncertainty_reserve_basis = Column(
        String(64), doc="Basis used for the W2 uncertainty reserve"
    )
    budget_soft_limit_ratio = Column(
        Float, doc="W2 soft input budget ratio"
    )
    budget_soft_input_budget_tokens = Column(
        Integer, doc="W2 soft input budget where proactive compression begins"
    )
    budget_hard_input_budget_tokens = Column(
        Integer, doc="W2 hard input budget consumed by W3 final fit"
    )
    budget_warnings = Column(
        JSONB, doc="Structured W2 budget warnings active for this request"
    )
    generation_rate = Column(
        Float, doc="Token generation rate (tokens per second)")
    is_streaming = Column(
        Boolean, default=False, doc="Whether the request used streaming"
    )
    is_success = Column(
        Boolean, default=True, doc="Whether the request completed successfully"
    )
    is_error = Column(
        Boolean, default=False, doc="Whether the request resulted in an error"
    )
    error_type = Column(
        String(50), doc="Error type classification (e.g., auth_error, rate_limit)"
    )
    error_message = Column(Text, doc="Error message details")
    retry_count = Column(Integer, default=0, doc="Number of retry attempts")
    operation = Column(
        String(50), doc="Operation type (e.g., llm_completion, llm_chat)"
    )
    create_time = Column(
        TIMESTAMP(timezone=False), server_default=func.now(), doc="Record creation time"
    )
    delete_flag = Column(String(1), default="N", doc="Soft delete flag: Y/N")
    display_name = Column(String(200), doc="User-facing model display name")
    model_type = Column(
        String(20), default="llm", doc="Model type: llm, embedding, multi_embedding"
    )


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
    labels = Column(JSONB, default=[], doc="JSON array of label strings for filtering/grouping tools")
    is_user_selectable = Column(
        Boolean, default=True, nullable=False, doc="Whether users can actively select the tool in agent configuration")
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
    version_no = Column(Integer, default=0, nullable=False, primary_key=True,
                        doc="Version number. 0 = draft/editing state, >=1 = published snapshot")
    name = Column(String(100), doc="Agent name")
    display_name = Column(String(100), doc="Agent display name")
    description = Column(Text, doc="Description")
    author = Column(String(100), doc="Agent author")
    model_ids = Column(
        ARRAY(Integer), doc="List of model IDs, foreign key references to model_record_t.model_id, max 5 models")
    max_steps = Column(Integer, doc="Maximum number of steps")
    duty_prompt = Column(Text, doc="Duty prompt content")
    constraint_prompt = Column(Text, doc="Constraint prompt content")
    few_shots_prompt = Column(Text, doc="Few shots prompt content")
    parent_agent_id = Column(Integer, doc="Parent Agent ID")
    tenant_id = Column(String(100), doc="Belonging tenant")
    enabled = Column(Boolean, doc="Enabled")
    is_main_agent = Column(Boolean, default=True, nullable=False, doc="Whether this agent is a main agent")
    provide_run_summary = Column(
        Boolean, doc="Whether to provide the running summary to the manager agent")
    business_description = Column(
        Text, doc="Manually entered by the user to describe the entire business process")
    business_logic_model_name = Column(
        String(100), doc="Model name used for business logic prompt generation")
    business_logic_model_id = Column(
        Integer, doc="Model ID used for business logic prompt generation, foreign key reference to model_record_t.model_id")
    prompt_template_id = Column(
        Integer, doc="Prompt template ID used for business logic prompt generation")
    prompt_template_name = Column(String(
        100), doc="Prompt template name used for business logic prompt generation")
    group_ids = Column(String, doc="Agent group IDs list")
    is_new = Column(Boolean, default=False, doc="Whether this agent is marked as new for the user")
    current_version_no = Column(Integer, nullable=True, doc="Current published version number. NULL means no version published yet")
    ingroup_permission = Column(String(30), doc=_INGROUP_PERMISSION_DOC)
    requested_output_tokens = Column(
        Integer,
        doc=(
            "Per-agent override for W2 requested_output_tokens. NULL means "
            "inherit the resolved model-level default."
        ),
    )
    enable_context_manager = Column(Boolean, default=True, doc="Whether to enable context management (compression) for this agent")
    is_a2a = Column(Boolean, default=False, nullable=False, doc="Whether to publish this agent as an A2A Server agent")
    verification_config = Column(JSONB, doc="Layered ReAct self-verification configuration")
    context_policy = Column(JSONB, doc="Agent-level context processing policy override")
    allow_chat_metadata = Column(
        Boolean,
        default=False,
        nullable=False,
        server_default=text("false"),
        doc="Whether Native Chat and Debug users may submit runtime metadata",
    )
    greeting_message = Column(Text, doc="Agent greeting message displayed on chat initial screen")
    example_questions = Column(JSONB, doc="List of example questions for starting a conversation with this agent")
    icon_url = Column(String(1024), doc="Object storage key for the agent icon")


class PromptTemplate(TableBase):
    """
    Prompt template table for user-defined prompt generation templates.
    """
    __tablename__ = "ag_prompt_template_t"
    __table_args__ = (
        Index(
            "uq_prompt_template_user_name_active",
            "tenant_id",
            "user_id",
            "template_name",
            unique=True,
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "idx_ag_prompt_template_t_user",
            "tenant_id",
            "user_id",
            "template_type",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        {"schema": SCHEMA},
    )

    template_id = Column(Integer, Sequence(
        "ag_prompt_template_t_template_id_seq", schema=SCHEMA), primary_key=True, nullable=False, autoincrement=True, doc="Prompt template ID")
    template_name = Column(String(100), nullable=False,
                           doc="Prompt template name")
    description = Column(String(500), doc="Prompt template description")
    template_type = Column(String(50), nullable=False,
                           default="agent_generate", doc="Prompt template type")
    tenant_id = Column(String(100), nullable=False, doc="Tenant ID")
    user_id = Column(String(100), nullable=False, doc="User ID")
    template_content_zh = Column(
        JSONB, nullable=False, doc="Chinese prompt template content")
    template_content_en = Column(JSONB, doc="English prompt template content")


class ToolInstance(TableBase):
    """
    Information table for tenant tool configuration.
    """
    __tablename__ = "ag_tool_instance_t"
    __table_args__ = {"schema": SCHEMA}

    tool_instance_id = Column(
        Integer,
        Sequence("ag_tool_instance_t_tool_instance_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="ID"
    )
    tool_id = Column(Integer, doc="Tenant tool ID")
    agent_id = Column(Integer, doc="Agent ID")
    params = Column(JSON, doc="Parameter configuration")
    user_id = Column(String(100), doc="User ID")
    tenant_id = Column(String(100), doc="Tenant ID")
    enabled = Column(Boolean, doc="Enabled")
    version_no = Column(Integer, default=0, primary_key=True, nullable=False,
                        doc="Version number. 0 = draft/editing state, >=1 = published snapshot")


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
    embedding_model_name = Column(String(
        200), doc="Embedding model name, used to record the embedding model used by the knowledge base")
    embedding_model_id = Column(
        Integer, doc="Embedding model ID, foreign key reference to model_record_t.model_id")
    tenant_id = Column(String(100), doc="Tenant ID")
    group_ids = Column(String, doc="Knowledge base group IDs list")
    ingroup_permission = Column(
        String(30), doc=_INGROUP_PERMISSION_DOC)
    summary_frequency = Column(String(10), nullable=True,
                               doc="Auto-summary frequency: '3h', '5h', '1d', '1w', or NULL (disabled)")
    last_summary_time = Column(TIMESTAMP(timezone=False), nullable=True,
                               doc="Timestamp of last summary generation")
    last_doc_update_time = Column(TIMESTAMP(timezone=False), nullable=True,
                                  doc="Timestamp of last document add/delete operation")
    preserve_source_file = Column(
        Boolean,
        default=True,
        doc="Whether to preserve uploaded source documents after vectorization",
    )
    quota_limit_bytes = Column(
        BigInteger, nullable=True,
        doc="Per-KB soft storage quota in bytes. NULL means no per-KB limit (shares tenant pool freely)."
    )


class KnowledgeStorageObject(TableBase):
    """Durable ownership and accounting record for one KB source object."""

    __tablename__ = "knowledge_storage_object_t"
    __table_args__ = (
        UniqueConstraint(
            "bucket_name",
            "object_name",
            name="uq_knowledge_storage_object_bucket_object",
        ),
        CheckConstraint(
            "raw_bytes >= 0",
            name="ck_knowledge_storage_object_raw_bytes_nonnegative",
        ),
        CheckConstraint(
            "status IN ('COMMITTED', 'DELETED')",
            name="ck_knowledge_storage_object_status",
        ),
        Index(
            "idx_knowledge_storage_object_tenant_active",
            "tenant_id",
            postgresql_where=text("delete_flag = 'N' AND status = 'COMMITTED'"),
        ),
        Index(
            "idx_knowledge_storage_object_kb_active",
            "tenant_id",
            "knowledge_id",
            postgresql_where=text("delete_flag = 'N' AND status = 'COMMITTED'"),
        ),
        {"schema": SCHEMA},
    )

    storage_object_id = Column(
        BigInteger,
        Sequence("knowledge_storage_object_t_storage_object_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="Storage object ledger ID",
    )
    create_time = Column(
        TIMESTAMP(timezone=False),
        nullable=False,
        server_default=func.now(),
        doc="Creation time",
    )
    update_time = Column(
        TIMESTAMP(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        doc="Update time",
    )
    delete_flag = Column(
        String(1),
        nullable=False,
        default="N",
        server_default=text("'N'"),
        doc="Whether it is deleted. Optional values: Y/N",
    )
    tenant_id = Column(String(100), nullable=False, doc="Tenant isolation key")
    knowledge_id = Column(BigInteger, nullable=False, doc="Owning knowledge base ID")
    index_name = Column(String(100), nullable=False, doc="Owning Elasticsearch index name")
    bucket_name = Column(String(255), nullable=False, doc="MinIO bucket name")
    object_name = Column(String(1024), nullable=False, doc="MinIO object name")
    raw_bytes = Column(BigInteger, nullable=False, doc="Authoritative MinIO object size in bytes")
    status = Column(
        String(20),
        nullable=False,
        default="COMMITTED",
        server_default=text("'COMMITTED'"),
        doc="Accounting lifecycle status: COMMITTED or DELETED",
    )


class KnowledgeFileLifecycle(TableBase):
    """Durable lifecycle record for one knowledge-base upload attempt."""

    __tablename__ = "knowledge_file_lifecycle_t"
    __table_args__ = (
        CheckConstraint(
            "status IN ('UPLOADING', 'UPLOADED', 'PROCESSING', 'FORWARDING', "
            "'FAILED', 'COMPLETED', 'DELETE_REQUESTED', 'DELETED')",
            name="ck_knowledge_file_lifecycle_status",
        ),
        Index(
            "idx_knowledge_file_lifecycle_kb_status",
            "tenant_id",
            "knowledge_id",
            "status",
        ),
        Index(
            "idx_knowledge_file_lifecycle_identity",
            "tenant_id",
            "index_name",
            "object_name",
        ),
        Index(
            "idx_knowledge_file_lifecycle_upload_recovery",
            "upload_owner_service",
            "create_time",
            postgresql_where=text(
                "delete_flag = 'N' AND status = 'UPLOADING'"
            ),
        ),
        Index(
            "uq_knowledge_file_lifecycle_active_identity",
            "tenant_id",
            "index_name",
            "object_name",
            unique=True,
            postgresql_where=text(
                "object_name IS NOT NULL AND status NOT IN ('DELETE_REQUESTED', 'DELETED')"
            ),
        ),
        {"schema": SCHEMA},
    )

    file_id = Column(String(64), primary_key=True, nullable=False, doc="Stable file lifecycle ID")
    tenant_id = Column(String(100), nullable=False, doc="Tenant isolation key")
    knowledge_id = Column(BigInteger, nullable=False, doc="Owning knowledge base ID")
    index_name = Column(String(100), nullable=False, doc="Owning Elasticsearch index")
    bucket_name = Column(String(255), nullable=True, doc="MinIO bucket")
    object_name = Column(String(1024), nullable=True, doc="MinIO object name")
    original_filename = Column(
        String(1024),
        nullable=False,
        doc="Effective filename used by processing and displayed to users",
    )
    file_size = Column(BigInteger, nullable=True, doc="Uploaded file size in bytes")
    upload_owner_service = Column(
        String(32),
        nullable=True,
        doc="Service that owns recovery of an in-progress upload",
    )
    uploaded_at = Column(TIMESTAMP(timezone=False), nullable=True, doc="Successful MinIO upload time")
    completed_at = Column(TIMESTAMP(timezone=False), nullable=True, doc="Successful ES indexing time")
    status = Column(
        String(30),
        nullable=False,
        default="UPLOADING",
        server_default=text("'UPLOADING'"),
        doc="File lifecycle status",
    )
    stage = Column(String(30), nullable=True, doc="Current processing stage")
    process_task_id = Column(String(64), nullable=True, doc="Process task ID")
    forward_task_id = Column(String(64), nullable=True, doc="Forward task ID")
    parent_task_id = Column(String(64), nullable=True, doc="Parent chain task ID")
    processing_attempt = Column(Integer, nullable=False, default=0, server_default=text("0"))
    error_code = Column(String(100), nullable=True, doc="Error code reported by the ingestion flow")
    error_message = Column(Text, nullable=True, doc="Raw failure summary when no error code exists")
    error_stage = Column(String(30), nullable=True, doc="Failure stage")
    failed_at = Column(TIMESTAMP(timezone=False), nullable=True, doc="Failure time")
    deleted_at = Column(TIMESTAMP(timezone=False), nullable=True, doc="Time when the record reached DELETED status")
    storage_object_id = Column(BigInteger, nullable=True, doc="Linked storage ledger ID")
    version = Column(Integer, nullable=False, default=0, server_default=text("0"), doc="Optimistic-lock version")


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


# ---------------------------------------------------------------------------
# Phase 2 Memory System tables
# ---------------------------------------------------------------------------

# Identifier lengths used by memory_records_t and memory_retrieval_hits_t.
# memory_id is auto-incremented by PostgreSQL (serial4) on insert; callers do
# not supply a value. ES mirrors it as `str(memory_id)` in the document `_id`.
class MemoryRecord(TableBase):
    """Internal memory records persisted in PostgreSQL.

    This is the authoritative store for agent short-term memory, which
    additionally mirrors the content into Elasticsearch (managed by
    ``services.memory_index_service``).

    The isolation contract from ``memory_design.md`` is enforced by the
    database access layer, not by the schema:
    - tenant layer:    tenant_id
    - user layer:      tenant_id + user_id
    - agent layer:     tenant_id + user_id + agent_id (+ conversation_id)
    """

    __tablename__ = "memory_records_t"
    __table_args__ = (
        Index("idx_memory_records_tenant", "tenant_id"),
        Index("idx_memory_records_user", "tenant_id", "user_id"),
        Index(
            "idx_memory_records_agent",
            "tenant_id",
            "user_id",
            "agent_id",
            "conversation_id",
        ),
        Index(
            "idx_memory_records_idempotency",
            "tenant_id",
            "idempotency_key",
        ),
        Index(
            "idx_memory_records_status",
            "tenant_id",
            "user_id",
            "layer",
            "status",
        ),
        {"schema": SCHEMA},
    )

    memory_id = Column(Integer, primary_key=True, nullable=False, autoincrement=True,
                        doc="Auto-incremented memory primary key (serial4).")
    tenant_id = Column(String(100), nullable=False,
                       doc="Tenant ID (isolation key).")
    user_id = Column(String(100), nullable=False,
                     doc="User ID (isolation key for user/agent layers).")
    agent_id = Column(String(100), nullable=True,
                      doc="Agent ID (isolation key for agent short-term layer).")
    conversation_id = Column(String(100), nullable=True,
                             doc="Conversation ID (further isolation key for agent).")

    layer = Column(String(30), nullable=False,
                   doc="Memory layer: tenant | user | agent.")
    memory_type = Column(String(30), nullable=True,
                         doc="Memory type: long_term | short_term.")
    status = Column(String(30), nullable=False, default="active",
                    doc="Status: active | archived | disabled.")

    content = Column(Text, nullable=False, doc="Memory content.")
    concept_tags = Column(ARRAY(Text), nullable=True,
                          doc="Optional concept tags from Dreaming REM phase.")

    es_index_name = Column(String(255), nullable=True,
                           doc="Elasticsearch index for agent short-term memory "
                               "(mem_{model_name}_{dimension}); null for PG-only layers.")

    create_time = Column(TIMESTAMP(timezone=False), server_default=func.now(),
                         doc="Creation timestamp.")
    update_time = Column(TIMESTAMP(timezone=False), server_default=func.now(),
                         onupdate=func.now(),
                         doc="Last update timestamp.")
    created_by = Column(String(100), nullable=True, doc="Creator user id.")
    updated_by = Column(String(100), nullable=True, doc="Last updater user id.")
    delete_flag = Column(String(1), nullable=False, default="N",
                         doc="Soft-delete flag (Y/N).")

    idempotency_key = Column(String(128), nullable=False,
                             doc="Idempotency key for write deduplication.")

    recall_count = Column(Integer, nullable=False, default=0,
                          doc="Total recall hit count.")
    daily_count = Column(Integer, nullable=False, default=0,
                         doc="Recall hit count for the most recent active day.")
    grounded_count = Column(Integer, nullable=False, default=0,
                            doc="Count of grounded (verified) recalls.")
    last_recalled_at = Column(TIMESTAMP(timezone=False), nullable=True,
                              doc="Most recent recall timestamp.")
    query_hashes = Column(ARRAY(Text), nullable=True,
                          doc="Hashes of queries that recalled this memory.")
    recall_days = Column(ARRAY(Text), nullable=True,
                         doc="ISO date strings of recall days.")

    light_hits = Column(Integer, nullable=False, default=0,
                        doc="Light Sleep phase hit count.")
    rem_hits = Column(Integer, nullable=False, default=0,
                      doc="REM Sleep phase hit count.")
    last_light_at = Column(TIMESTAMP(timezone=False), nullable=True,
                           doc="Last Light Sleep timestamp.")
    last_rem_at = Column(TIMESTAMP(timezone=False), nullable=True,
                         doc="Last REM Sleep timestamp.")


class MemoryLongTermVersion(TableBase):
    """Immutable Markdown long-term memory shared by tenant and user scopes."""

    __tablename__ = "memory_long_term_version_t"
    __table_args__ = (
        CheckConstraint("scope IN ('tenant', 'user')", name="ck_memory_long_term_scope"),
        Index(
            "uq_memory_long_term_version_scope_no",
            "tenant_id", "scope", "subject_id", "version_no", unique=True,
        ),
        Index(
            "uq_memory_long_term_active_scope",
            "tenant_id", "scope", "subject_id", unique=True,
            postgresql_where=text("is_active AND delete_flag = 'N'"),
        ),
        Index("uq_memory_long_term_run", "dreaming_run_id", unique=True,
              postgresql_where=text("dreaming_run_id IS NOT NULL")),
        {"schema": SCHEMA},
    )

    version_id = Column(BigInteger, Sequence(
        "memory_long_term_version_t_version_id_seq", schema=SCHEMA), primary_key=True)
    tenant_id = Column(String(100), nullable=False)
    scope = Column(String(20), nullable=False)
    subject_id = Column(String(100), nullable=False)
    version_no = Column(Integer, nullable=False)
    parent_version_id = Column(BigInteger)
    is_active = Column(Boolean, nullable=False, default=False)
    content = Column(Text, nullable=False)
    source = Column(String(20), nullable=False)
    author_user_id = Column(String(100), nullable=False)
    editor_user_id = Column(String(100), nullable=False)
    authored_at = Column(TIMESTAMP(timezone=False), nullable=False, server_default=func.now())
    dreaming_run_id = Column(BigInteger)
    character_count = Column(Integer, nullable=False)
    raw_dreaming_input = Column(Text)
    generation_audit = Column(JSONB, nullable=False, default=dict)
    evidence_ids = Column(JSONB, nullable=False, default=list)
    fallback_details = Column(JSONB, nullable=False, default=dict)
    omission_details = Column(JSONB, nullable=False, default=dict)


class MemoryRetrievalHit(TableBase):
    """Per-hit memory retrieval log row, sourced by ``search_memory`` tools.

    Phase 2 only writes rows from internal PG-backed recalls. Dreaming
    aggregates these rows in batch to update ``memory_records_t`` statistics.
    """

    __tablename__ = "memory_retrieval_hits_t"
    __table_args__ = (
        Index("idx_memory_retrieval_hits_memory", "memory_id", "occurred_at"),
        Index(
            "idx_memory_retrieval_hits_tenant_user_agent",
            "tenant_id",
            "user_id",
            "agent_id",
            "day",
        ),
        {"schema": SCHEMA},
    )

    hit_id = Column(Integer, primary_key=True, nullable=False, autoincrement=True,
                    doc="Hit primary key (serial4).")
    tenant_id = Column(String(100), nullable=True, doc="Tenant ID.")
    user_id = Column(String(100), nullable=True, doc="User ID.")
    agent_id = Column(String(100), nullable=True, doc="Agent ID.")
    conversation_id = Column(String(100), nullable=True,
                             doc="Conversation ID.")
    memory_id = Column(Integer, nullable=True,
                       doc="Recalled memory id (null on miss rows).")
    query_text = Column(Text, nullable=True,
                        doc="Original search query text.")
    query_hash = Column(String(128), nullable=True,
                        doc="Stable hash of the query text.")
    retrieval_score = Column(Numeric(38, 18), nullable=True,
                             doc="Similarity score reported by the backend.")
    source = Column(String(100), nullable=False, default="nexent",
                    doc="Hit origin: nexent | external_provider.")
    occurred_at = Column(TIMESTAMP(timezone=False), nullable=False,
                         server_default=func.now(),
                         doc="Time the hit was recorded.")
    day = Column(String(100), nullable=True,
                 doc="ISO date string (occurred_at::date).")
    grounded = Column(Boolean, nullable=False, default=False,
                      doc="Whether the hit was verified/grounded.")
    create_time = Column(TIMESTAMP(timezone=False), nullable=True,
                         server_default=func.now(),
                         doc="Row creation time.")
    update_time = Column(TIMESTAMP(timezone=False), nullable=True,
                         server_default=func.now(),
                         doc="Row last update time.")
    created_by = Column(String(100), nullable=True,
                        doc="User that created the row.")
    updated_by = Column(String(100), nullable=True,
                        doc="User that last updated the row.")
    delete_flag = Column(String(1), nullable=False, default="N",
                         doc="Soft delete flag (N = active, Y = deleted).")


class MemoryDreamingAudit(TableBase):
    """One durable audit row per manual or scheduled Dreaming run."""

    __tablename__ = "memory_dreaming_audit_t"
    __table_args__ = (
        Index(
            "idx_memory_dreaming_audit_scope",
            "tenant_id",
            "user_id",
            "agent_id",
            "started_at",
        ),
        {"schema": SCHEMA},
    )

    run_id = Column(
        BigInteger,
        Sequence("memory_dreaming_audit_t_run_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
    )
    tenant_id = Column(String(100), nullable=False)
    user_id = Column(String(100), nullable=False)
    agent_id = Column(String(100), nullable=False)
    trigger_source = Column(String(30), nullable=False, default="manual")
    status = Column(String(30), nullable=False, default="running")
    current_phase = Column(String(30))
    started_at = Column(TIMESTAMP(timezone=False), nullable=False, server_default=func.now())
    finished_at = Column(TIMESTAMP(timezone=False))
    light_count = Column(Integer, nullable=False, default=0)
    rem_count = Column(Integer, nullable=False, default=0)
    promoted_count = Column(Integer, nullable=False, default=0)
    deferred_count = Column(Integer, nullable=False, default=0)
    published_version_id = Column(BigInteger)
    reason = Column(String(100))
    error = Column(Text)
    lock_owner = Column(String(100), nullable=True)
    lock_until = Column(TIMESTAMP(timezone=False), nullable=True)


class MemoryDreamingDecision(TableBase):
    """One normalized candidate decision produced by a Dreaming run."""

    __tablename__ = "memory_dreaming_decision_t"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "decision_order",
            name="uq_memory_dreaming_decision_run_order",
        ),
        Index("idx_memory_dreaming_decision_memory", "memory_id"),
        {"schema": SCHEMA},
    )

    decision_id = Column(
        BigInteger,
        Sequence("memory_dreaming_decision_t_decision_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
    )
    run_id = Column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.memory_dreaming_audit_t.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    decision_order = Column(Integer, nullable=False)
    memory_id = Column(BigInteger, nullable=False)
    score = Column(Float, nullable=False)
    noise = Column(Boolean, nullable=False, default=False)
    signal_count = Column(Integer, nullable=False, default=0)
    context_diversity = Column(Integer, nullable=False, default=0)
    evidence_ids = Column(ARRAY(String(100)), nullable=False, default=list)
    event = Column(String(20), nullable=False)
    reason = Column(String(100), nullable=False)
    archive_suggested = Column(Boolean, nullable=False, default=False)


class MemoryDreamingSchedule(TableBase):
    """Persistent automatic Dreaming schedule for one user/agent scope."""

    __tablename__ = "memory_dreaming_schedule_t"
    __table_args__ = (
        Index(
            "uq_memory_dreaming_schedule_scope",
            "tenant_id",
            "user_id",
            "agent_id",
            unique=True,
        ),
        Index(
            "idx_memory_dreaming_schedule_due",
            "enabled",
            "next_fire_at",
        ),
        {"schema": SCHEMA},
    )

    schedule_id = Column(
        BigInteger,
        Sequence("memory_dreaming_schedule_t_schedule_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
    )
    tenant_id = Column(String(100), nullable=False)
    user_id = Column(String(100), nullable=False)
    agent_id = Column(String(100), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    rule_type = Column(String(20), nullable=False, default="CRON")
    timezone = Column(String(100), nullable=False, default="Asia/Shanghai")
    start_at = Column(TIMESTAMP(timezone=False), nullable=False)
    cron_expr = Column(String(100))
    interval_seconds = Column(Integer)
    next_fire_at = Column(TIMESTAMP(timezone=False))
    last_fire_at = Column(TIMESTAMP(timezone=False))
    fire_count = Column(Integer, nullable=False, default=0)
    min_score = Column(Float, nullable=True)
    min_recall_count = Column(Integer, nullable=True)
    min_unique_queries = Column(Integer, nullable=True)
    source_limit = Column(Integer, nullable=True)
    long_term_max_chars = Column(Integer, nullable=True)
    summarization_max_attempts = Column(Integer, nullable=True)


class MemoryProviderConfig(TableBase):
    """External memory provider configuration."""

    __tablename__ = "memory_provider_config_t"
    __table_args__ = (
        Index("uq_memory_provider_config_tenant_name", "tenant_id", "provider_name",
              unique=True, postgresql_where=text("delete_flag = 'N'")),
        Index("idx_memory_provider_config_enabled", "tenant_id", "enabled",
              postgresql_where=text("delete_flag = 'N'")),
        {"schema": SCHEMA},
    )

    provider_config_id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(100), nullable=False)
    provider_name = Column(String(100), nullable=False)
    connection_type = Column(String(20), nullable=False, default="plugin")
    enabled = Column(Boolean, nullable=False, default=False)
    timeout_seconds = Column(Integer, nullable=False, default=30)
    last_error_code = Column(String(50))


class MemoryProviderConfigParam(TableBase):
    """EAV parameters for external memory provider configuration."""

    __tablename__ = "memory_provider_config_param_t"
    __table_args__ = (
        Index("idx_provider_config_param_provider", "provider_config_id",
              postgresql_where=text("delete_flag = 'N'")),
        Index("uq_provider_config_param_name", "provider_config_id", "param_name",
              unique=True, postgresql_where=text("delete_flag = 'N'")),
        {"schema": SCHEMA},
    )

    param_id = Column(Integer, primary_key=True, autoincrement=True)
    provider_config_id = Column(Integer, nullable=False)
    param_name = Column(String(200), nullable=False)
    param_value = Column(Text)


class MemoryExternalIngestEventLog(TableBase):
    """Audit log for external memory ingest events."""

    __tablename__ = "memory_external_ingest_event_log_t"
    __table_args__ = (
        Index("idx_external_ingest_log_tenant", "tenant_id", "user_id", "agent_id", "sent_at"),
        Index("idx_external_ingest_log_idem", "idempotency_key",
              unique=True, postgresql_where=text("delete_flag = 'N'")),
        {"schema": SCHEMA},
    )

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(100))
    tenant_id = Column(String(100))
    user_id = Column(String(100))
    agent_id = Column(String(100))
    conversation_id = Column(String(100))
    event_id = Column(String(255))
    idempotency_key = Column(Text)
    unit_ids = Column(Text)
    response_status = Column(String(30))
    response_summary = Column(Text)
    sent_at = Column(TIMESTAMP(timezone=False), server_default=func.now())


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
    mcp_name = Column(String(100), doc=_MCP_NAME_DOC)
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
    container_port = Column(
        Integer,
        doc="Host port bound for containerized MCP service",
    )
    authorization_token = Column(
        String(500),
        doc="Authorization token for MCP server authentication (e.g., Bearer token)",
        default=None,
    )
    custom_headers = Column(
        JSON,
        doc="Custom HTTP headers as JSON object for MCP server requests",
        default=None,
    )
    source = Column(
        String(30), doc="Source type: local/mcp_registry/community")
    market_id = Column(Integer, doc="Published market record ID (FK to mcp_market_record_t)")
    registry_json = Column(JSONB, doc="Full MCP registry server.json snapshot")
    config_json = Column(JSON, doc="MCP config data")
    enabled = Column(Boolean, default=True, doc="Enabled")
    tags = Column(ARRAY(Text), doc="Tags")
    description = Column(Text, doc="Description")
    group_ids = Column(String, doc="Comma-separated group IDs that can access this MCP")
    ingroup_permission = Column(String(30), default="READ_ONLY",
                                 doc="In-group permission: EDIT, READ_ONLY, PRIVATE")
    shared_fields = Column(JSON, default=None,
                           doc="JSON object of field-level sharing flags (e.g. {\"serverUrl\": true, \"authorizationToken\": false})")


class McpCommunityRecord(TableBase):
    """Community MCP market records table."""

    __tablename__ = "mcp_community_record_t"
    __table_args__ = {"schema": SCHEMA}

    community_id = Column(
        Integer,
        Sequence("mcp_community_record_t_community_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="Community record ID, unique primary key",
    )
    tenant_id = Column(String(100), doc=_PUBLISHER_TENANT_ID_DOC)
    user_id = Column(String(100), doc=_PUBLISHER_USER_ID_DOC)
    mcp_name = Column(String(100), doc=_MCP_NAME_DOC)
    mcp_server = Column(String(500), doc="MCP server URL")
    source = Column(String(30), doc="Source type, fixed to community")
    registry_json = Column(JSONB, doc="Full MCP metadata JSON")
    transport_type = Column(
        String(30), doc="Transport type: http/sse/container")
    config_json = Column(JSON, doc="Public-shareable MCP configuration JSON")
    review_status = Column(
        String(30), default="pending", doc="Review status: pending/approved/rejected/offline")
    review_type = Column(
        String(30), default="initial_listing", doc="Review submission type: initial_listing/update")
    tags = Column(ARRAY(Text), doc="Tags")
    description = Column(Text, doc="Description")


class McpMarketRecord(TableBase):
    """MCP market (community) record — single table covering all listing states."""

    __tablename__ = "mcp_market_record_t"
    __table_args__ = {"schema": SCHEMA}

    market_id = Column(
        BigInteger,
        Sequence("mcp_market_record_t_market_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="Market record ID, unique primary key",
    )
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    user_id = Column(String(100), nullable=False, doc="Publisher user ID")
    mcp_name = Column(String(100), doc=_MCP_NAME_DOC)
    mcp_server = Column(String(500), doc="MCP server URL")
    source = Column(String(30), doc="Source type, fixed to community")
    registry_json = Column(JSONB, doc="Full MCP metadata JSON")
    transport_type = Column(String(30), doc="Transport type: http/sse/container")
    config_json = Column(JSON, doc="Public-shareable MCP configuration JSON")
    tags = Column(ARRAY(Text), doc="Tags")
    description = Column(Text, doc="Description")
    content = Column(Text, doc="Listing note on submit or review opinion on approve/reject")
    download_count = Column(Integer, default=0, doc="Cumulative download/install count")
    review_status = Column(String(30), default="not_shared",
                           doc="Listing status: not_shared / pending_review / rejected / shared")
    submitted_by = Column(String(100), doc="Submitter email when listing enters pending_review")
    source_mcp_id = Column(Integer, doc="Local MCP record ID that created this market record")
    group_ids = Column(String, doc="Comma-separated group IDs that can access this MCP")
    ingroup_permission = Column(String(30), default="READ_ONLY",
                                 doc="In-group permission: EDIT, READ_ONLY, PRIVATE")
    shared_fields = Column(JSON, default=None,
                           doc="Snapshot of shared_fields at submission time")


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
    user_role = Column(
        String(30), doc="User role: SUPER_ADMIN, ADMIN, DEV, USER")
    user_email = Column(String(255), doc="User email address")


class AgentRelation(TableBase):
    """
    Agent parent-child relationship table
    Primary key: (relation_id, version_no)
    """
    __tablename__ = "ag_agent_relation_t"
    __table_args__ = {"schema": SCHEMA}

    relation_id = Column(Integer, Sequence("ag_agent_relation_t_relation_id_seq", schema=SCHEMA),
                         primary_key=True, nullable=False, doc="Relationship ID, primary key")
    version_no = Column(Integer, primary_key=True, default=0, nullable=False,
                        doc="Version number. 0 = draft/editing state, >=1 = published snapshot")
    selected_agent_id = Column(
        Integer, doc="Selected agent ID")
    parent_agent_id = Column(Integer, doc="Parent agent ID")
    tenant_id = Column(String(100), doc="Tenant ID")
    selected_agent_version_no = Column(
        Integer, nullable=True,
        doc="Pinned version of selected_agent_id. NULL = runtime fallback to child current_version_no",
    )


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
                primary_key=True, nullable=False, doc=_PRIMARY_KEY_DOC)
    tenant_id = Column(String(100), nullable=False, doc="Tenant ID")
    agent_id = Column(Integer, nullable=False, doc="Agent ID")
    version_no = Column(Integer, nullable=False,
                        doc="Version number, starts from 1. Does not include 0 (draft)")
    version_name = Column(
        String(100), doc="User-defined version name for display")
    release_note = Column(Text, doc="Release notes / publish remarks")
    source_version_no = Column(
        Integer, doc="Source version number. If this version is a rollback, record the source version")
    source_type = Column(String(
        30), doc="Source type: NORMAL (normal publish) / ROLLBACK (rollback and republish)")
    status = Column(String(30), default="RELEASED",
                    doc="Version status: RELEASED / DISABLED / ARCHIVED")


class AgentRepository(TableBase):
    """
    Agent repository (marketplace) table. Frozen snapshot of a published agent tree for sharing.
    """
    __tablename__ = "ag_agent_repository_t"
    __table_args__ = {"schema": SCHEMA}

    agent_repository_id = Column(BigInteger, Sequence("ag_agent_repository_t_agent_repository_id_seq", schema=SCHEMA),
                                 primary_key=True, nullable=False, doc="Agent repository listing ID, unique primary key")
    publisher_tenant_id = Column(String(100), nullable=False, doc=_PUBLISHER_TENANT_ID_DOC)
    publisher_user_id = Column(String(100), nullable=False, doc=_PUBLISHER_USER_ID_DOC)
    agent_id = Column(Integer, nullable=False,
                      doc="Root agent ID from ag_tenant_agent_t; upsert key")
    version_no = Column(Integer, nullable=False,
                        doc="Published version number frozen at share time")
    name = Column(String(100), nullable=False,
                  doc="Root agent programmatic name for display and search")
    display_name = Column(String(100), doc="Root agent display name")
    description = Column(Text, doc="Root agent description")
    author = Column(String(100), doc="Agent author")
    submitted_by = Column(String(100), doc="Submitter email when listing enters pending_review")
    tags = Column(ARRAY(Text), doc="Marketplace tags")
    tool_count = Column(Integer,
                        doc="Total tool count across all agents in the bundle (display only)")
    icon = Column(String(100), doc="Marketplace card icon (emoji or URL)")
    downloads = Column(Integer, default=0,
                       doc="Marketplace download/copy count for card display")
    version_name = Column(String(100),
                          doc="Repository entry version name for display (from ag_tenant_agent_version_t)")
    agent_info_json = Column(JSONB, nullable=False,
                             doc="Frozen ExportAndImportDataFormat snapshot with optional skills")
    status = Column(String(30), default="not_shared",
                    doc="Listing status: not_shared (未共享) / pending_review (待审核) / rejected (审核驳回) / shared (已共享)")
    content = Column(Text, doc="Listing note on submit or review opinion on approve/reject")


class SkillRepository(TableBase):
    """
    Skill repository (marketplace) table. Frozen snapshot of a shared skill for installation.
    """
    __tablename__ = "ag_skill_repository_t"
    __table_args__ = {"schema": SCHEMA}

    skill_repository_id = Column(BigInteger, Sequence("ag_skill_repository_t_skill_repository_id_seq", schema=SCHEMA),
                                 primary_key=True, nullable=False, doc="Skill repository listing ID, unique primary key")
    publisher_tenant_id = Column(String(100), nullable=False, doc=_PUBLISHER_TENANT_ID_DOC)
    publisher_user_id = Column(String(100), nullable=False, doc=_PUBLISHER_USER_ID_DOC)
    skill_id = Column(Integer, nullable=False, doc="Source skill ID from ag_skill_info_t")
    name = Column(String(100), nullable=False, doc="Skill name for display and search")
    description = Column(Text, doc="Skill description")
    source = Column(String(30), doc="Skill source")
    submitted_by = Column(String(100), doc="Submitter email when listing enters pending_review")
    category_id = Column(Integer, doc="Optional marketplace category ID")
    tags = Column(ARRAY(Text), doc="Marketplace tags")
    icon = Column(String(100), doc="Marketplace card icon (emoji or URL)")
    downloads = Column(Integer, default=0, doc="Marketplace install count for card display")
    skill_info_json = Column(JSONB, nullable=False, doc="Frozen skill metadata snapshot")
    skill_zip_base64 = Column(Text, nullable=False, doc="Frozen skill ZIP payload encoded as base64")
    status = Column(String(30), default="not_shared",
                    doc="Listing status: not_shared / pending_review / rejected / shared")
    content = Column(Text, doc="Listing note on submit or review opinion on approve/reject")


class UserTokenInfo(TableBase):
    """
    User token (AK/SK) information table
    """
    __tablename__ = "user_token_info_t"
    __table_args__ = (
        Index("ux_user_token_access_key", "access_key", unique=True),
        Index("ix_user_token_user_active", "user_id", "delete_flag"),
        {"schema": SCHEMA},
    )

    token_id = Column(Integer, Sequence("user_token_info_t_token_id_seq", schema=SCHEMA),
                      primary_key=True, nullable=False, doc="Token ID, unique primary key")
    access_key = Column(String(100), nullable=False, doc="Access Key (AK)")
    user_id = Column(String(100), nullable=False,
                     doc="User ID who owns this token")


class UserTokenUsageLog(TableBase):
    """
    User token usage log table
    """
    __tablename__ = "user_token_usage_log_t"
    __table_args__ = (
        Index(
            "ix_user_token_usage_active_token_time",
            "token_id",
            text("create_time DESC"),
            postgresql_include=["token_usage_id"],
            postgresql_where=text("delete_flag = 'N'"),
        ),
        {"schema": SCHEMA},
    )

    token_usage_id = Column(Integer, Sequence("user_token_usage_log_t_token_usage_id_seq", schema=SCHEMA),
                            primary_key=True, nullable=False, doc="Token usage log ID, unique primary key")
    token_id = Column(Integer, nullable=False,
                      doc="Foreign key to user_token_info_t.token_id")
    call_function_name = Column(
        String(100), doc="API function name being called")
    related_id = Column(
        Integer, doc="Related resource ID (e.g., conversation_id)")
    meta_data = Column(
        JSONB, doc="Additional metadata for this usage log entry, stored as JSON")


class UserOAuthAccount(TableBase):
    __tablename__ = "user_oauth_account_t"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id",
                         name="uq_oauth_provider_user"),
        {"schema": SCHEMA},
    )

    oauth_account_id = Column(
        Integer,
        Sequence("user_oauth_account_t_oauth_account_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="OAuth account ID, primary key",
    )
    user_id = Column(String(100), nullable=False, doc="Supabase user UUID")
    provider = Column(
        String(30), nullable=False, doc="OAuth provider name: github, wechat, gde, link_app"
    )
    provider_user_id = Column(
        String(200), nullable=False, doc="User ID from the OAuth provider"
    )
    provider_email = Column(
        String(255), doc="Email address from the OAuth provider")
    provider_username = Column(
        String(200), doc="Display name from the OAuth provider")
    tenant_id = Column(String(100), doc="Tenant ID at time of linking")


class UserCasSession(TableBase):
    __tablename__ = "user_cas_session_t"
    __table_args__ = (
        Index("ix_user_cas_session_session_id", "session_id"),
        Index("ix_user_cas_session_user_id", "user_id"),
        Index("ix_user_cas_session_cas_user_id", "cas_user_id"),
        {"schema": SCHEMA},
    )

    cas_session_id = Column(
        Integer,
        Sequence("user_cas_session_t_cas_session_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="CAS session record ID",
    )
    session_id = Column(String(100), nullable=False, unique=True, doc="JWT session ID")
    user_id = Column(String(100), nullable=False, doc="Supabase user UUID")
    cas_user_id = Column(String(200), nullable=False, doc="User ID from CAS")
    cas_session_index = Column(String(500), doc="CAS SessionIndex or service ticket")
    status = Column(String(30), nullable=False, default="active", doc="active/revoked")
    expires_at = Column(TIMESTAMP(timezone=False), nullable=False, doc="Session expiration time")
    revoked_at = Column(TIMESTAMP(timezone=False), doc="Revocation time")


class SkillInfo(TableBase):
    """
    Skill information table - stores skill metadata and content.
    """
    __tablename__ = "ag_skill_info_t"
    __table_args__ = (
        Index(
            "uq_skill_info_tenant_name_active",
            "tenant_id",
            "skill_name",
            unique=True,
            postgresql_where=text(
                "tenant_id IS NOT NULL AND delete_flag = 'N'"
            ),
        ),
        Index(
            "uq_skill_info_global_name_active",
            "skill_name",
            unique=True,
            postgresql_where=text(
                "tenant_id IS NULL AND delete_flag = 'N'"
            ),
        ),
        {"schema": SCHEMA},
    )

    skill_id = Column(Integer, Sequence("ag_skill_info_t_skill_id_seq", schema=SCHEMA),
                      primary_key=True, nullable=False, autoincrement=True, doc="Skill ID")
    skill_name = Column(String(100), nullable=False,
                        doc="Skill name, unique among active skills within its tenant scope")
    tenant_id = Column(String(100), nullable=True,
                       doc="Tenant ID for multi-tenancy. NULL for pre-existing skills.")
    skill_description = Column(String(1000), doc="Skill description")
    skill_tags = Column(JSON, doc="Skill tags as JSON array")
    skill_content = Column(Text, doc="Skill content in markdown format")
    config_schemas = Column(
        JSON, doc="Parameter metadata from config/schema.yaml")
    config_values = Column(
        JSON, doc="Runtime parameter values from config/config.yaml")
    source = Column(String(30), nullable=False, default="official",
                    doc="Skill source: official, custom, etc.")
    group_ids = Column(String, doc="Skill group IDs list")
    ingroup_permission = Column(String(30), doc=_INGROUP_PERMISSION_DOC)


class SkillToolRelation(TableBase):
    """
    Skill-Tool relation table - many-to-many relationship between skills and tools.
    """
    __tablename__ = "ag_skill_tools_rel_t"
    __table_args__ = {"schema": SCHEMA}

    rel_id = Column(Integer, Sequence("ag_skill_tools_rel_t_rel_id_seq", schema=SCHEMA),
                    primary_key=True, nullable=False, autoincrement=True, doc="Relation ID")
    skill_id = Column(Integer, nullable=False,
                      doc="Foreign key to ag_skill_info_t.skill_id")
    tool_id = Column(Integer, nullable=False,
                     doc="Foreign key to ag_tool_info_t.tool_id")


class SkillInstance(TableBase):
    """
    Skill instance table - stores per-agent skill configuration.
    Similar to ToolInstance, stores skill settings for each agent version.
    Note: skill_description and skill_content removed - these are now retrieved from ag_skill_info_t.
    """
    __tablename__ = "ag_skill_instance_t"
    __table_args__ = {"schema": SCHEMA}

    skill_instance_id = Column(
        Integer,
        Sequence("ag_skill_instance_t_skill_instance_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc="Skill instance ID"
    )
    skill_id = Column(Integer, nullable=False,
                      doc="Foreign key to ag_skill_info_t.skill_id")
    agent_id = Column(Integer, nullable=False, doc="Agent ID")
    user_id = Column(String(100), doc="User ID")
    tenant_id = Column(String(100), doc="Tenant ID")
    enabled = Column(Boolean, default=True,
                     doc="Whether this skill is enabled for the agent")
    version_no = Column(Integer, default=0, primary_key=True, nullable=False,
                        doc="Version number. 0 = draft/editing state, >=1 = published snapshot")
    config_values = Column(
        JSON, doc="Per-agent runtime parameter values (mirrors ag_tool_instance_t.params)")
    config_schemas = Column(
        JSON, doc="Per-agent parameter schema overrides from config/schema.yaml")


class OuterApiService(TableBase):
    """
    OpenAPI service table - stores MCP service information converted from OpenAPI specs.
    Each record represents one MCP service with its OpenAPI specification.
    """
    __tablename__ = "ag_outer_api_services"
    __table_args__ = {"schema": SCHEMA}

    id = Column(BigInteger, Sequence("ag_outer_api_services_id_seq", schema=SCHEMA),
                primary_key=True, nullable=False, doc="Service ID, unique primary key")
    mcp_service_name = Column(String(100), nullable=False,
                              doc="MCP service name (unique identifier per tenant)")
    description = Column(Text, doc="Service description from OpenAPI info")
    openapi_json = Column(JSONB, doc="Complete OpenAPI JSON specification")
    server_url = Column(String(500), doc="Base URL of the REST API server")
    headers_template = Column(JSONB, doc="Default headers template as JSON")
    tenant_id = Column(String(100), nullable=False,
                       doc="Tenant ID for multi-tenancy")
    is_available = Column(Boolean, default=True,
                          doc="Whether the service is available")


# Alias for backward compatibility
OuterApiTool = OuterApiService


class A2ANacosConfig(TableBase):
    """
    Nacos configuration for external A2A agent discovery.
    Stores connection info and discovery scope.
    """
    __tablename__ = "ag_a2a_nacos_config_t"
    __table_args__ = {"schema": SCHEMA}

    id = Column(BigInteger, primary_key=True,
                autoincrement=True, doc=_PRIMARY_KEY_DOC)
    config_id = Column(String(64), unique=True, nullable=False,
                       doc="Unique config identifier for API reference")

    # Nacos connection
    nacos_addr = Column(String(512), nullable=False,
                        doc="Nacos server address, e.g., http://nacos-server:8848")
    nacos_username = Column(
        String(100), doc="Nacos username for authentication")
    nacos_password = Column(
        String(256), doc="Nacos password, encrypted at rest")

    # Discovery scope
    namespace_id = Column(String(100), default="public",
                          doc="Nacos namespace for service discovery")

    # Metadata
    name = Column(String(100), nullable=False,
                  doc="Display name for this Nacos config")
    description = Column(Text, doc="Description of this Nacos configuration")

    # Tenant isolation
    tenant_id = Column(String(100), nullable=False,
                       doc="Tenant ID for multi-tenancy")

    # Status
    is_active = Column(Boolean, default=True,
                       doc="Whether this Nacos config is active")
    last_scan_at = Column(TIMESTAMP(timezone=False),
                          doc="Last time a scan was performed using this config")


class A2AExternalAgent(TableBase):
    """
    External A2A agents discovered from URL or Nacos.
    Caches Agent Cards for A2A Client role.
    """
    __tablename__ = "ag_a2a_external_agent_t"
    __table_args__ = {"schema": SCHEMA}

    id = Column(BigInteger, primary_key=True,
                autoincrement=True, doc=_PRIMARY_KEY_DOC)

    # Agent metadata (cached from Agent Card)
    name = Column(String(255), nullable=False,
                  doc="Agent name from Agent Card")
    description = Column(Text, doc="Agent description from Agent Card")
    version = Column(
        String(50), doc="Agent version from Agent Card, e.g., 1.2.0")

    # Primary interface (extracted from supportedInterfaces for quick access)
    # In A2A 1.0, this should store the http-json-rpc URL
    agent_url = Column(String(512), nullable=False,
                       doc="Primary A2A endpoint URL (http-json-rpc by default)")

    # Protocol type for calling this agent: JSONRPC, HTTP+JSON, GRPC
    protocol_type = Column(String(20), default=PROTOCOL_JSONRPC,
                           doc="Protocol type for calling this agent")

    # Capabilities
    streaming = Column(Boolean, default=False,
                       doc="Whether this agent supports SSE streaming")

    # All supported interfaces (full JSON array from Agent Card)
    # Format: [{protocolBinding, url, protocolVersion}, ...]
    supported_interfaces = Column(JSON, doc="All supported interfaces array")

    # Source information
    source_type = Column(String(20), nullable=False,
                         doc="Discovery source: url or nacos")

    # For URL mode
    source_url = Column(String(512), doc="Direct URL to agent card")
    agent_card_headers = Column(
        JSON,
        doc="Headers used only to retrieve and refresh the Agent Card"
    )

    # Security declared by the Agent Card and credentials configured by the user
    security_schemes = Column(JSON, doc="Security schemes declared by the Agent Card")
    security_requirements = Column(JSON, doc="Security requirements declared by the Agent Card")
    security_credentials = Column(
        JSON,
        doc="Credential values for Agent Card security schemes, never exposed by APIs"
    )
    selected_security_requirement_index = Column(
        Integer,
        doc="Selected Agent Card security requirement index used for external agent calls"
    )

    # For Nacos mode
    nacos_config_id = Column(
        String(64), doc="Reference to Nacos config used for discovery")
    nacos_agent_name = Column(
        String(255), doc="Original name used for Nacos query")

    # Base URL for infrastructure health checks
    base_url = Column(String(
        512), doc="Base URL for health checks (service root address), e.g., http://agent:8080")

    # Tenant isolation
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)

    # Full original Agent Card
    raw_card = Column(JSON, doc="Full original Agent Card JSON from discovery")

    # Cache management
    cached_at = Column(TIMESTAMP(timezone=False),
                       doc="Timestamp when Agent Card was cached")
    cache_expires_at = Column(
        TIMESTAMP(timezone=False), doc="Timestamp when cache expires")

    # Health check status
    is_available = Column(Boolean, default=True,
                          doc="Whether this agent is currently reachable")
    last_check_at = Column(TIMESTAMP(timezone=False),
                           doc="Last health check timestamp")
    last_check_result = Column(
        String(50), doc="Last health check result: OK, ERROR, TIMEOUT")


class A2AExternalAgentRelation(TableBase):
    """
    Relation between local agent and external A2A agent.
    Enables local agents to call external A2A agents as sub-agents.
    """
    __tablename__ = "ag_a2a_external_agent_relation_t"
    __table_args__ = (
        UniqueConstraint(
            "local_agent_id", "external_agent_id",
            name="uq_local_external_agent",
            deferrable=True,
        ),
        {"schema": SCHEMA},
    )

    id = Column(BigInteger, primary_key=True,
                autoincrement=True, doc=_PRIMARY_KEY_DOC)

    # Local agent (parent)
    local_agent_id = Column(Integer, nullable=False,
                            doc="Local parent agent ID")

    # External A2A agent (sub-agent) - FK to ag_a2a_external_agent_t.id
    external_agent_id = Column(
        BigInteger, nullable=False, doc="External A2A agent ID (FK to ag_a2a_external_agent_t.id)")

    # Tenant isolation
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)

    # Status
    is_enabled = Column(Boolean, default=True,
                        doc="Whether this relation is active")


class A2AServerAgent(TableBase):
    """
    Local agents registered as A2A Server endpoints.
    Exposes Agent Cards for external A2A callers.
    """
    __tablename__ = "ag_a2a_server_agent_t"
    __table_args__ = {"schema": SCHEMA}

    id = Column(BigInteger, primary_key=True,
                autoincrement=True, doc=_PRIMARY_KEY_DOC)

    # Link to local agent
    agent_id = Column(Integer, nullable=False, doc="Local agent ID")

    # Ownership
    user_id = Column(String(100), nullable=False, doc="Owner user ID")
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)

    # Generated endpoint ID
    endpoint_id = Column(String(64), unique=True,
                         nullable=False, doc="Generated endpoint ID")

    # Basic info (extracted from local agent, can be overridden)
    name = Column(String(255), nullable=False,
                  doc="Agent name exposed in Agent Card")
    description = Column(Text, doc="Agent description exposed in Agent Card")
    version = Column(String(50), doc="Agent version exposed in Agent Card")

    # Primary endpoint URL (http-json-rpc by default)
    agent_url = Column(
        String(512), doc="Primary A2A endpoint URL (http-json-rpc by default)")

    # Capabilities
    streaming = Column(Boolean, default=False,
                       doc="Whether this agent supports SSE streaming")

    # All supported interfaces (A2A 1.0 compliant)
    # Format: [{protocolBinding, url, protocolVersion}, ...]
    supported_interfaces = Column(
        JSON, doc="All supported interfaces: [{protocolBinding, url, protocolVersion}, ...]")

    # Agent Card customization (partial overrides only)
    card_overrides = Column(
        JSON, doc="User customizations for Agent Card (partial override)")

    # A2A Server status
    is_enabled = Column(Boolean, default=False,
                        doc="Whether A2A Server is enabled for this agent")

    # Raw Agent Card (generated from settings, for debugging)
    raw_card = Column(JSON, doc="Generated Agent Card JSON (for debugging)")

    # Publishing timestamps
    published_at = Column(TIMESTAMP(timezone=False),
                          doc="Timestamp when A2A Server was last enabled")
    unpublished_at = Column(TIMESTAMP(timezone=False),
                            doc="Timestamp when A2A Server was disabled")


class A2ATask(SimpleTableBase):
    """
    A2A tasks for tracking requests.
    Task is the unit of work, not all requests need to create a task.
    """
    __tablename__ = "ag_a2a_task_t"
    __table_args__ = {"schema": SCHEMA}

    # Core identifiers (following A2A spec)
    id = Column(String(64), primary_key=True, doc="Task ID (A2A spec: taskId)")
    context_id = Column(
        String(64), doc="Context ID for grouping related tasks")

    # Endpoint and caller info
    endpoint_id = Column(String(64), nullable=False, doc="Endpoint ID")
    caller_user_id = Column(String(100), doc="User ID of the caller")
    caller_tenant_id = Column(String(100), doc="Tenant ID of the caller")

    # Request data
    raw_request = Column(JSON, doc="Original A2A request payload")

    # Task state (following A2A TaskState enum)
    task_state = Column(String(50), nullable=False, server_default="TASK_STATE_SUBMITTED",
                        doc="Task state: TASK_STATE_SUBMITTED, TASK_STATE_WORKING, TASK_STATE_COMPLETED, TASK_STATE_FAILED, TASK_STATE_CANCELED, TASK_STATE_INPUT_REQUIRED, TASK_STATE_REJECTED, TASK_STATE_AUTH_REQUIRED")
    state_timestamp = Column(TIMESTAMP(timezone=False),
                             doc="Task state last update timestamp")

    # Task result
    result_data = Column(JSON, doc="Task final result data")

    # Timestamps
    create_time = Column(TIMESTAMP(timezone=False),
                         server_default=func.now(), doc="Task creation timestamp")
    update_time = Column(TIMESTAMP(timezone=False), server_default=func.now(
    ), onupdate=func.now(), doc="Task last update timestamp")
    completed_at = Column(TIMESTAMP(timezone=False),
                          doc="Task completion timestamp")


class A2AMessage(SimpleTableBase):
    """
    A2A messages within tasks.
    Stores conversation history for multi-turn interactions.
    """
    __tablename__ = "ag_a2a_message_t"
    __table_args__ = {"schema": SCHEMA}

    # Core identifiers (following A2A spec)
    message_id = Column(String(64), primary_key=True,
                        doc="Message ID (A2A spec: messageId)")
    task_id = Column(String(64), nullable=True,
                     doc="Task ID this message belongs to (nullable for standalone/simple requests)")

    # Message attributes
    message_index = Column(Integer, nullable=False,
                           doc="Order of message in the conversation")
    role = Column(String(20), nullable=False,
                  doc="Message sender role: user or agent")

    # Message content (following A2A Part structure)
    parts = Column(JSON, nullable=False,
                   doc="Message parts following A2A Part structure")
    meta_data = Column(JSON, doc="Optional metadata")
    extensions = Column(JSON, doc="Extension URI list")

    # References to other tasks (optional)
    reference_task_ids = Column(
        JSON, doc="Referenced task IDs array for multi-turn scenarios")

    # Timestamp
    create_time = Column(TIMESTAMP(
        timezone=False), server_default=func.now(), doc="Message creation timestamp")


class A2AArtifact(SimpleTableBase):
    """
    A2A artifacts. Stores the output/artifacts produced by a task.
    """
    __tablename__ = "ag_a2a_artifact_t"
    __table_args__ = {"schema": SCHEMA}

    # Core identifiers (following A2A spec)
    id = Column(String(64), primary_key=True, doc="Internal primary key")
    artifact_id = Column(String(64), nullable=False,
                         doc="Artifact ID (A2A spec: artifactId)")
    task_id = Column(String(64), nullable=False,
                     doc="Task ID this artifact belongs to")

    # Artifact attributes
    name = Column(String(255), doc="Human-readable artifact name")
    description = Column(Text, doc="Artifact description")
    parts = Column(JSON, nullable=False,
                   doc="Artifact parts following A2A Part structure")
    meta_data = Column(JSON, doc="Artifact metadata")
    extensions = Column(JSON, doc="Extension URI list")

    # Timestamp
    create_time = Column(TIMESTAMP(timezone=False), server_default=func.now(), doc="Artifact creation timestamp")


# -----------------------------------------------------------------------------
# Agent Evaluation (offline) tables
# -----------------------------------------------------------------------------
class EvaluationSet(TableBase):
    """Evaluation set metadata."""

    __tablename__ = "evaluation_set_t"
    __table_args__ = {"schema": SCHEMA}

    evaluation_set_id = Column(
        BigInteger,
        Sequence("evaluation_set_t_evaluation_set_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc=_PRIMARY_KEY_DOC,
    )

    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    name = Column(String(255), nullable=False, doc="Evaluation set name")
    description = Column(Text, doc="Evaluation set description")

    source_filename = Column(String(255), doc="Original uploaded filename")
    case_count = Column(Integer, default=0, doc="Total number of cases")
    generation_status = Column(String(20), default="IDLE", doc="IDLE / GENERATING / DONE / FAILED")
    generation_progress = Column(Integer, default=0, doc="Generation progress 0-100")

    __table_args__ = (
        Index("ix_eval_set_tenant_id", "tenant_id"),
        Index("ix_eval_set_name", "tenant_id", "name"),
        {"schema": SCHEMA},
    )


class EvaluationSetCase(TableBase):
    """Evaluation cases belonging to a set."""

    __tablename__ = "evaluation_set_case_t"
    __table_args__ = {"schema": SCHEMA}

    evaluation_set_case_id = Column(
        BigInteger,
        Sequence("evaluation_set_case_t_evaluation_set_case_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc=_PRIMARY_KEY_DOC,
    )

    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    evaluation_set_id = Column(BigInteger, nullable=False, doc="Evaluation set id")

    case_id = Column(String(128), doc="External case_id from JSONL (optional)")

    inputs = Column(JSONB, nullable=False, doc="Case inputs JSON")
    label = Column(JSONB, nullable=False, doc="Case label JSON")

    order_no = Column(Integer, default=0, doc="Case order in the set")
    session_id = Column(String(128), nullable=True, doc="Multi-turn session identifier")
    turn_order = Column(Integer, default=0, doc="Turn order within a session (1-based)")

    __table_args__ = (
        Index("ix_eval_set_case_set_id", "evaluation_set_id"),
        Index("ix_eval_set_case_tenant_id", "tenant_id"),
        {"schema": SCHEMA},
    )


class AgentEvaluation(TableBase):
    """An evaluation run for a specific agent and evaluation set."""

    __tablename__ = "agent_evaluation_t"
    __table_args__ = {"schema": SCHEMA}

    agent_evaluation_id = Column(
        BigInteger,
        Sequence("agent_evaluation_t_agent_evaluation_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc=_PRIMARY_KEY_DOC,
    )

    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)

    agent_id = Column(Integer, nullable=False, doc="Agent id")
    agent_version_no = Column(Integer, nullable=False, doc="Published agent version_no used for evaluation")

    evaluation_set_id = Column(BigInteger, nullable=False, doc="Evaluation set id")

    status = Column(
        String(30),
        nullable=False,
        default="PENDING",
        doc="Run status: PENDING/RUNNING/COMPLETED/FAILED",
    )

    progress_total = Column(Integer, default=0, doc="Total cases")
    progress_done = Column(Integer, default=0, doc="Completed cases")

    judge_model_id = Column(
        Integer,
        doc=(
            "Model id used by the judge. Persisted so the background worker can "
            "recover it after restart and the frontend can resolve judge_model_name."
        ),
    )

    score_overall = Column(Float, doc="Overall score (0-1)")

    error_message = Column(Text, doc="Failure reason")
    pass_count = Column(Integer, default=0, doc="Number of passed cases")
    fail_count = Column(Integer, default=0, doc="Number of failed cases")
    evaluator_config = Column(JSONB, doc="Multi-evaluator config: {evaluator_ids, field_mappings}")
    analysis_report = Column(JSONB, doc="AI-generated analysis report")
    annotation_schema_ids = Column(JSONB, default=[], doc="Enabled annotation schema IDs")

    __table_args__ = (
        Index("ix_agent_eval_tenant_id", "tenant_id"),
        Index("ix_agent_eval_agent_id", "tenant_id", "agent_id"),
        Index("ix_agent_eval_set_id", "tenant_id", "evaluation_set_id"),
        Index("ix_agent_eval_judge_model_id", "tenant_id", "judge_model_id"),
        {"schema": SCHEMA},
    )


class AgentEvaluationCase(TableBase):
    """Per-case evaluation details within an evaluation run."""

    __tablename__ = "agent_evaluation_case_t"
    __table_args__ = {"schema": SCHEMA}

    agent_evaluation_case_id = Column(
        BigInteger,
        Sequence("agent_evaluation_case_t_agent_evaluation_case_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc=_PRIMARY_KEY_DOC,
    )

    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)

    agent_evaluation_id = Column(BigInteger, nullable=False, doc="Evaluation run id")
    evaluation_set_case_id = Column(BigInteger, nullable=False, doc="Evaluation set case id")

    inputs = Column(JSONB, nullable=False, doc="Case inputs snapshot (query only for pass cases)")
    label = Column(JSONB, nullable=False, doc="Case label snapshot (cleared to {answer:''} for pass cases)")
    predict = Column(JSONB, doc="Predict JSON (answer/raw); NULL for pass cases")

    score = Column(JSONB, doc="Case score (float or dict for multi-evaluator)")
    reason = Column(Text, doc="Judge reason; NULL for pass cases")
    pass_status = Column(
        String(16),
        doc="Judge result: pass / fail. Pass cases have predict/reason/label.answer cleared to save space.",
    )

    status = Column(
        String(30),
        nullable=False,
        default="PENDING",
        doc="Case status: PENDING/RUNNING/COMPLETED/FAILED",
    )
    error_message = Column(Text, doc="Per-case failure reason")
    session_id = Column(String(128), nullable=True, doc="Multi-turn session identifier")
    turn_order = Column(Integer, default=0, doc="Turn order within a session (0-indexed)")

    __table_args__ = (
        Index("ix_agent_eval_case_eval_id", "agent_evaluation_id"),
        Index("ix_agent_eval_case_tenant_id", "tenant_id"),
        Index("ix_agent_eval_case_pass_status", "tenant_id", "agent_evaluation_id", "pass_status"),
        {"schema": SCHEMA},
    )


class Evaluator(TableBase):
    """Evaluator definition for agent evaluation tasks."""

    __tablename__ = "evaluator_t"
    __table_args__ = (
        Index("ix_evaluator_tenant", "tenant_id", "delete_flag"),
        Index("ix_evaluator_status", "tenant_id", "status", "delete_flag"),
        {"schema": SCHEMA},
    )

    evaluator_id = Column(
        BigInteger,
        Sequence("evaluator_t_evaluator_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
    )
    tenant_id = Column(String(100), nullable=False, default="", doc="Tenant ID; empty = system builtin")
    name = Column(String(255), nullable=False, doc="Evaluator name (zh)")
    description = Column(Text, doc="Evaluator description (zh)")
    name_en = Column(String(255), doc="Evaluator name (en)")
    description_en = Column(Text, doc="Evaluator description (en)")
    evaluator_type = Column(String(20), nullable=False, default="llm", doc="llm / code")
    source = Column(String(20), nullable=False, default="custom", doc="builtin / custom")
    prompt = Column(Text, doc="LLM evaluator prompt template (zh)")
    code = Column(Text, doc="Code/runtime evaluator Python function")
    score_range_min = Column(Float, default=0.0)
    score_range_max = Column(Float, default=1.0)
    pass_threshold = Column(Float, default=0.5, doc="Score >= threshold = pass")
    input_fields = Column(JSONB, nullable=False, default=[], doc='[{name, type, required}]')
    status = Column(String(20), nullable=False, default="DRAFT", doc="DRAFT / PUBLISHED")
    version_no = Column(Integer, nullable=False, default=1)
    version_group_id = Column(BigInteger, doc="Groups versions of the same evaluator; NULL until first publish")
    is_current = Column(Boolean, default=True, doc="True if this is the current active version")
    model_id = Column(Integer, doc="LLM model ID; NULL = use task-level judge")


class EvaluationAnnotationSchema(TableBase):
    """Label/annotation template for evaluation cases."""

    __tablename__ = "evaluation_annotation_schema_t"
    __table_args__ = {"schema": SCHEMA}

    schema_id = Column(BigInteger, Sequence("evaluation_annotation_schema_t_schema_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, default="")
    name = Column(String(50), nullable=False)
    description = Column(String(200))
    annotation_type = Column(String(20), nullable=False, default="classification", doc="classification/boolean/number/text")
    options = Column(JSONB, doc="For classification: [{\"label\":\"正确\"},...]")


class EvaluationAnnotation(TableBase):
    """Single annotation value for an evaluation case."""

    __tablename__ = "evaluation_annotation_t"
    __table_args__ = {"schema": SCHEMA}

    annotation_id = Column(BigInteger, Sequence("evaluation_annotation_t_annotation_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, default="")
    agent_evaluation_id = Column(BigInteger, nullable=True, doc="Denormalized for efficient cascade-delete")
    case_id = Column(BigInteger, nullable=False)
    schema_id = Column(BigInteger, nullable=False)
    value = Column(Text)


class Notification(TableBase):
    """
    In-app notification message table. One row per message; actual per-user
    delivery and read state live in notification_receiver_t (fan-out).
    """
    __tablename__ = "notification_t"

    notification_id = Column(
        BigInteger,
        Sequence("notification_t_notification_id_seq", schema=SCHEMA),
        primary_key=True, nullable=False,
        doc="Notification ID, unique primary key")
    event_type = Column(String(50), nullable=False,
                        doc="Event type, e.g. repository_review_approved / repository_review_rejected")
    resource_type = Column(String(50), nullable=False,
                           doc="Resource type, e.g. agent_repository / skill_repository / mcp_repository")
    unique_id = Column(BigInteger,
                       doc="Related resource primary key (e.g. agent_repository_id)")
    details = Column(JSONB, doc="i18n interpolation details for the event template")
    scope = Column(String(20), nullable=False,
                          doc="Audience scope: SU / TENANT / TENANT_ADMIN / USER")
    tenant_id = Column(String(100),
                              doc="tenant for TENANT / TENANT_ADMIN scope; NULL for SU")
    is_active = Column(Boolean, nullable=False, default=True,
                       doc="Whether this notification is still active/valid")

    __table_args__ = (
        Index(
            "ix_notification_event_resource_unique_active",
            "event_type", "resource_type", "unique_id", "is_active",
        ),
        {"schema": SCHEMA},
    )


class NotificationReceiver(TableBase):
    """
    Per-user notification delivery and read status (fan-out from notification_t).
    """
    __tablename__ = "notification_receiver_t"

    receiver_id = Column(
        BigInteger,
        Sequence("notification_receiver_t_receiver_id_seq", schema=SCHEMA),
        primary_key=True, nullable=False,
        doc="Receiver row ID, unique primary key")
    notification_id = Column(BigInteger, nullable=False,
                             doc="FK to notification_t.notification_id")
    receiver_user_id = Column(String(100), nullable=False,
                               doc="Receiver user ID")
    tenant_id = Column(String(100), doc=_TENANT_ID_DOC)
    is_read = Column(Boolean, default=False,
                     doc="Whether this receiver has read the notification")

    __table_args__ = (
        Index("ix_notification_receiver_user_read", "receiver_user_id", "is_read"),
        Index("ix_notification_receiver_notification_id", "notification_id"),
        {"schema": SCHEMA},
    )


class TagBucket(TableBase):
    """Tenant-owned fixed tag library."""

    __tablename__ = "tag_bucket"
    __table_args__ = (
        CheckConstraint("btrim(tenant_id) <> ''"),
        CheckConstraint("status IN ('active', 'disabled')"),
        CheckConstraint("delete_flag IN ('N', 'Y')"),
        UniqueConstraint("tenant_id", "bucket_id", name="uq_tag_bucket_tenant_id"),
        UniqueConstraint("tenant_id", "bucket_key", name="uq_tag_bucket_tenant_key"),
        {"schema": SCHEMA},
    )

    bucket_id = Column(BigInteger, primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    bucket_key = Column(String(100), nullable=False)
    bucket_name = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    delete_flag = Column(String(1), nullable=False, server_default=text("'N'"))


class DocumentTagProjection(TableBase):
    """Provider-facing synchronization ledger for knowledge document tag projections."""

    __tablename__ = "document_tag_projection"
    __table_args__ = (
        CheckConstraint("btrim(tenant_id) <> ''"),
        CheckConstraint("provider IN ('local', 'aidp')"),
        CheckConstraint("btrim(knowledge_base_id) <> ''"),
        CheckConstraint("btrim(provider_document_id) <> ''"),
        CheckConstraint("status IN ('pending', 'synced', 'failed', 'unsupported')"),
        UniqueConstraint(
            "tenant_id",
            "provider",
            "knowledge_base_id",
            "provider_document_id",
            name="uq_document_tag_projection_identity",
        ),
        Index(
            "idx_document_tag_projection_tenant_status",
            "tenant_id",
            "status",
            "next_attempt_at",
        ),
        Index(
            "idx_document_tag_projection_kb",
            "tenant_id",
            "provider",
            "knowledge_base_id",
        ),
        Index(
            "idx_document_tag_projection_resource",
            "tenant_id",
            "resource_id",
        ),
        {"schema": SCHEMA},
    )

    projection_id = Column(BigInteger, primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    provider = Column(String(20), nullable=False)
    knowledge_base_id = Column(String(255), nullable=False)
    provider_document_id = Column(String(512), nullable=False)
    resource_id = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    version = Column(BigInteger, nullable=False, server_default=text("0"))
    payload = Column(JSONB, nullable=False, server_default=text("'[]'::JSONB"))
    retry_count = Column(Integer, nullable=False, server_default=text("0"))
    last_error = Column(Text)
    last_attempt_at = Column(TIMESTAMP(timezone=True))
    next_attempt_at = Column(TIMESTAMP(timezone=True))


class TagBucketResourceType(TableBase):
    """Immutable tenant-local binding from a resource type to a tag library."""

    __tablename__ = "tag_bucket_resource_type"
    __table_args__ = (
        CheckConstraint("btrim(tenant_id) <> ''"),
        CheckConstraint(
            "resource_type IN ('agent', 'skill', 'tool', 'mcp_service', 'knowledge_base', 'knowledge_document')"
        ),
        CheckConstraint("status IN ('active', 'disabled')"),
        CheckConstraint("delete_flag IN ('N', 'Y')"),
        UniqueConstraint("tenant_id", "bucket_resource_type_id", name="uq_tag_bucket_resource_type_tenant_id"),
        UniqueConstraint("tenant_id", "bucket_id", "resource_type", name="uq_tag_bucket_resource_type"),
        ForeignKeyConstraint(
            ["tenant_id", "bucket_id"],
            ["nexent.tag_bucket.tenant_id", "nexent.tag_bucket.bucket_id"],
            name="fk_tag_bucket_resource_type_bucket",
        ),
        {"schema": SCHEMA},
    )

    bucket_resource_type_id = Column(BigInteger, primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    bucket_id = Column(BigInteger, nullable=False)
    resource_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    delete_flag = Column(String(1), nullable=False, server_default=text("'N'"))


class TagDefinition(TableBase):
    """A controlled tag key within one tenant tag library."""

    __tablename__ = "tag_definition"
    __table_args__ = (
        CheckConstraint("btrim(tenant_id) <> ''"),
        CheckConstraint("selection_mode IN ('single_select', 'multi_select', 'no_value')"),
        CheckConstraint("status IN ('active', 'disabled')"),
        CheckConstraint("delete_flag IN ('N', 'Y')"),
        UniqueConstraint("tenant_id", "definition_id", name="uq_tag_definition_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "bucket_id"],
            ["nexent.tag_bucket.tenant_id", "nexent.tag_bucket.bucket_id"],
            name="fk_tag_definition_bucket",
        ),
        Index("idx_tag_definition_bucket", "tenant_id", "bucket_id", "delete_flag"),
        Index(
            "uq_tag_definition_active_key",
            "tenant_id",
            "bucket_id",
            "definition_key",
            unique=True,
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "uq_tag_definition_active_normalized_name",
            "tenant_id",
            "bucket_id",
            "normalized_name",
            unique=True,
            postgresql_where=text("delete_flag = 'N'"),
        ),
        {"schema": SCHEMA},
    )

    definition_id = Column(BigInteger, primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    bucket_id = Column(BigInteger, nullable=False)
    definition_key = Column(String(100), nullable=False)
    definition_name = Column(String(255), nullable=False)
    normalized_name = Column(
        Text(collation="C"),
        Computed('lower(btrim(definition_name) COLLATE "C")', persisted=True),
        nullable=False,
    )
    selection_mode = Column(String(20), nullable=False)
    sort_order = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    delete_flag = Column(String(1), nullable=False, server_default=text("'N'"))


class TagValue(TableBase):
    """A controlled value belonging to one tag definition."""

    __tablename__ = "tag_value"
    __table_args__ = (
        CheckConstraint("btrim(tenant_id) <> ''"),
        CheckConstraint("btrim(normalized_value) <> ''"),
        CheckConstraint("btrim(display_value) <> ''"),
        CheckConstraint("status IN ('active', 'disabled')"),
        CheckConstraint("delete_flag IN ('N', 'Y')"),
        UniqueConstraint("tenant_id", "value_id", "definition_id", name="uq_tag_value_tenant_id_definition"),
        ForeignKeyConstraint(
            ["tenant_id", "definition_id"],
            ["nexent.tag_definition.tenant_id", "nexent.tag_definition.definition_id"],
            name="fk_tag_value_definition",
        ),
        Index("idx_tag_value_definition", "tenant_id", "definition_id", "delete_flag"),
        Index(
            "uq_tag_value_active_normalized_value",
            "tenant_id",
            "definition_id",
            "normalized_value",
            unique=True,
            postgresql_where=text("delete_flag = 'N'"),
        ),
        {"schema": SCHEMA},
    )

    value_id = Column(BigInteger, primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    definition_id = Column(BigInteger, nullable=False)
    normalized_value = Column(Text, nullable=False)
    display_value = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    delete_flag = Column(String(1), nullable=False, server_default=text("'N'"))


class ResourceTagAssignment(TableBase):
    """A resource's binding to one controlled tag value."""

    __tablename__ = "resource_tag_assignment"
    __table_args__ = (
        CheckConstraint("btrim(tenant_id) <> ''"),
        CheckConstraint(
            "resource_type IN ('agent', 'skill', 'tool', 'mcp_service', 'knowledge_base', 'knowledge_document')"
        ),
        CheckConstraint("btrim(resource_id) <> ''"),
        CheckConstraint("status IN ('active', 'disabled')"),
        CheckConstraint("delete_flag IN ('N', 'Y')"),
        UniqueConstraint("tenant_id", "assignment_id", name="uq_resource_tag_assignment_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "resource_type",
            "resource_id",
            "value_id",
            name="uq_resource_tag_assignment_resource_value",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "definition_id"],
            ["nexent.tag_definition.tenant_id", "nexent.tag_definition.definition_id"],
            name="fk_resource_tag_assignment_definition",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "value_id", "definition_id"],
            [
                "nexent.tag_value.tenant_id",
                "nexent.tag_value.value_id",
                "nexent.tag_value.definition_id",
            ],
            name="fk_resource_tag_assignment_value_definition",
        ),
        Index("idx_resource_tag_assignment_resource", "tenant_id", "resource_type", "resource_id", "delete_flag"),
        Index("idx_resource_tag_assignment_definition", "tenant_id", "definition_id", "delete_flag"),
        {"schema": SCHEMA},
    )

    assignment_id = Column(BigInteger, primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(Text, nullable=False)
    definition_id = Column(BigInteger, nullable=False)
    value_id = Column(BigInteger, nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    delete_flag = Column(String(1), nullable=False, server_default=text("'N'"))
