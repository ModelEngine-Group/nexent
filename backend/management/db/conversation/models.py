# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Column,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    text,
)


from sqlalchemy.dialects.postgresql import JSONB


from management.db.base import SCHEMA, TableBase


class ConversationRecord(TableBase):
    """
    Overall information table for Q&A conversations
    """
    __tablename__ = "conversation_record_t"
    __table_args__ = {"schema": SCHEMA}

    conversation_id = Column(Integer, Sequence(
        "conversation_record_t_conversation_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    conversation_title = Column(String(100), doc="Conversation title")
    title_version = Column(
        Integer, nullable=False, server_default=text("0"),
        comment="Monotonic title revision; every stored rename advances it independently of activity",
    )
    last_activity_time = Column(
        TIMESTAMP(timezone=False), nullable=True,
        comment="Last committed visible message activity as a UTC timestamp; NULL falls back to conversation creation",
    )
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
    workbench_config = Column(
        JSONB,
        nullable=True,
        doc="Canonical schema-v4 Workbench resource declaration",
    )
    workbench_pinned_at = Column(
        TIMESTAMP(timezone=False), nullable=True,
        comment="Personal Workbench pin time as a UTC timestamp; NULL means unpinned; independent of conversation activity",
    )
    workbench_config_version = Column(
        Integer,
        nullable=False,
        server_default=text("0"),
        doc="Monotonic version of the canonical Workbench declaration",
    )

    selected_model_id = Column(Integer, nullable=True, comment="Root model selected for this Agent conversation; NULL inherits the Agent default.")
    model_parameter_preferences = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"),
        comment="Explicit parameter preferences keyed by outlet ID; no credentials or default-value copies.")
    model_parameter_preferences_version = Column(Integer, nullable=False, server_default=text("0"),
        comment="Optimistic revision of model preferences, independent of metadata and Workbench configuration.")


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
    message_source = Column(
        String(16), nullable=False, server_default=text("'CHAT'"),
        comment="Trusted message origin: CHAT consumes the ordinary user-turn quota; AUTOMATION is exempt",
    )
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
        14, 6), doc="Overall retrieval score between the source and the user query")
    score_accuracy = Column(Numeric(7, 6), doc="Accuracy score")
    score_semantic = Column(Numeric(7, 6), doc="Semantic similarity score")
    retrieval_highlight_terms = Column(
        JSONB,
        doc="Exact lexical terms returned by the retrieval engine for source highlighting",
    )
    aidp_metadata = Column(
        JSONB, nullable=True,
        comment="Opaque AIDP metadata snapshot returned for this retrieval hit",
    )
    aidp_source_reference = Column(
        JSONB, nullable=True,
        comment="AIDP source reference attributes for this retrieval hit, excluding metadata",
    )
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
