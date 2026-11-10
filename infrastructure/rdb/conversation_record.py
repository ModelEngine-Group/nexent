# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import TIMESTAMP, Column, Integer, Sequence, String, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.rdb.base import SCHEMA, TableBase


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
        doc="Canonical schema-v3 Workbench conversation declaration",
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
