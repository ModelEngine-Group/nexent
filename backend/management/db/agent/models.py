# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Integer,
    Sequence,
    String,
    Text,
    text,
)


from sqlalchemy.dialects.postgresql import ARRAY, JSONB


from management.db.base import (
    SCHEMA,
    TableBase,
    _INGROUP_PERMISSION_DOC,
    _PRIMARY_KEY_DOC,
    _PUBLISHER_TENANT_ID_DOC,
    _PUBLISHER_USER_ID_DOC,
)


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
    system_key = Column(
        String(100),
        doc="Stable platform-owned Agent key; NULL for user-created Agents",
    )
    agent_origin = Column(
        String(20),
        default="USER",
        nullable=False,
        server_default=text("'USER'"),
        doc="Agent ownership origin: USER or SYSTEM",
    )
    system_revision = Column(
        String(100),
        doc="Server-controlled Nexent release revision for a system Agent",
    )
    display_name = Column(String(100), doc="Agent display name")
    description = Column(Text, doc="Description")
    author = Column(String(100), doc="Agent author")
    model_ids = Column(
        ARRAY(Integer), doc="List of model IDs, foreign key references to model_record_t.model_id, max 5 models")
    max_steps = Column(Integer, doc="Maximum number of steps")
    duty_prompt = Column(Text, doc="Duty prompt content")
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
    enable_protocol_repair_retry = Column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
        comment="Whether this agent uses strict output validation and silent protocol repair",
    )
    is_a2a = Column(Boolean, default=False, nullable=False, doc="Whether to publish this agent as an A2A Server agent")
    verification_config = Column(JSONB, doc="Layered ReAct self-verification configuration")
    context_policy = Column(JSONB, doc="Agent-level context processing policy override")
    # v2.6.0 per-agent model inference param overrides.
    # Shape: {"<model_id>": {"temperature": 0.5, "top_p": null, "extra_params": {...}}}.
    model_params_override = Column(JSONB, doc="Per-agent overrides for model inference params. NULL means inherit model defaults.")
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
    icon_url = Column(String(1024), doc="Repository icon URL")
    downloads = Column(Integer, default=0,
                       doc="Marketplace download/copy count for card display")
    version_name = Column(String(100),
                          doc="Repository entry version name for display (from ag_tenant_agent_version_t)")
    agent_info_json = Column(JSONB, nullable=False,
                             doc="Frozen ExportAndImportDataFormat snapshot with optional skills")
    status = Column(String(30), default="not_shared",
                    doc="Listing status: not_shared (未共享) / pending_review (待审核) / rejected (审核驳回) / shared (已共享)")
    content = Column(Text, doc="Listing note on submit or review opinion on approve/reject")
