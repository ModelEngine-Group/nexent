# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    Column,
    Float,
    Index,
    Integer,
    Sequence,
    String,
    Text,
)


from sqlalchemy.dialects.postgresql import JSONB


from sqlalchemy.sql import func


from management.db.base import SCHEMA, SimpleTableBase


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
    effective_input_limit_tokens = Column(
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
    budget_schema_version = Column(
        Integer, doc="Version of the persisted context-budget contract"
    )
    budget_effective_input_limit_tokens = Column(
        Integer, doc="Effective input limit after applying the output reserve"
    )
    budget_uncertainty_reserve_tokens = Column(
        Integer, doc="Additional W2 uncertainty reserve deducted from input budget"
    )
    budget_uncertainty_reserve_basis = Column(
        String(64), doc="Basis used for the W2 uncertainty reserve"
    )
    budget_compaction_trigger_ratio = Column(
        Float, doc="Compaction Trigger Threshold ratio"
    )
    budget_compaction_trigger_ratio_source = Column(
        String(32), doc="Source of the Compaction Trigger Threshold ratio"
    )
    budget_compaction_trigger_threshold_tokens = Column(
        Integer, doc="Effective input token threshold that triggers compaction"
    )
    budget_compaction_target_ratio = Column(
        Float, doc="Compaction Target ratio"
    )
    budget_compaction_target_ratio_source = Column(
        String(32), doc="Source of the Compaction Target ratio"
    )
    budget_compaction_target_tokens = Column(
        Integer, doc="Desired effective input token count after compaction"
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
