# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import time
from typing import Optional

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
    and_,
    or_,
    select,
)


from sqlalchemy.dialects.postgresql import JSONB


from sqlalchemy.sql import func


from infrastructure.rdb.base import SCHEMA, SimpleTableBase
from infrastructure.rdb.model_record import ModelRecord


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


def write_model_monitoring_record(record: dict) -> None:
    """Save one SDK record in its own transaction."""
    from infrastructure.rdb.client import get_monitoring_db_session

    with get_monitoring_db_session() as session:
        record = dict(record)
        record["model_id"] = resolve_model_id(session, record)
        session.add(ModelMonitoringRecord(**record))
        session.flush()


# The SDK only knows the model names used on the wire, not the configuration
# row that produced them, so monitoring records arrive without ``model_id``.
# Resolving it here keeps every producer (LLM, embedding, client wrappers)
# consistent without pushing database ids through the SDK.
_MODEL_ID_CACHE_TTL_SECONDS = 60.0
_MODEL_ID_CACHE_MAX_ENTRIES = 512
_model_id_cache: dict[tuple, tuple[float, Optional[int]]] = {}

# ``multi_embedding`` is the SDK-side name of an embedding config that also
# accepts multimodal input; the configuration row still stores ``embedding``.
_MODEL_TYPE_ALIASES = {"multi_embedding": ("multi_embedding", "embedding")}


def resolve_model_id(session, record: dict) -> Optional[int]:
    """Return the model configuration id that produced this record, if known.

    Matching prefers the configured ``display_name``. When the producer only
    reported the provider model path (``display_name`` is missing or equal to
    ``model_name``, as embedding models do), the unique
    ``model_repo/model_name`` row is used instead. Ambiguous matches stay
    ``None`` rather than attributing traffic to the wrong configuration.
    """
    explicit = record.get("model_id")
    if explicit is not None:
        return explicit

    tenant_id = record.get("tenant_id")
    display_name = record.get("display_name") or ""
    model_name = record.get("model_name") or ""
    if not tenant_id or not (display_name or model_name):
        return None

    model_type = record.get("model_type") or ""
    model_types = _MODEL_TYPE_ALIASES.get(
        model_type, (model_type,) if model_type else ())
    cache_key = (tenant_id, model_types, display_name, model_name)
    now = time.monotonic()
    cached = _model_id_cache.get(cache_key)
    if cached is not None and cached[0] > now:
        return cached[1]

    model_id = None
    if display_name:
        model_id = _unique_model_id(
            session,
            tenant_id,
            model_types,
            ModelRecord.display_name == display_name,
        )
    if model_id is None and model_name and display_name in ("", model_name):
        model_path = ModelRecord.model_repo + "/" + ModelRecord.model_name
        model_id = _unique_model_id(
            session,
            tenant_id,
            model_types,
            or_(
                model_path == model_name,
                and_(
                    or_(
                        ModelRecord.model_repo.is_(None),
                        ModelRecord.model_repo == "",
                    ),
                    ModelRecord.model_name == model_name,
                ),
            ),
        )

    if len(_model_id_cache) >= _MODEL_ID_CACHE_MAX_ENTRIES:
        _model_id_cache.clear()
    _model_id_cache[cache_key] = (
        now + _MODEL_ID_CACHE_TTL_SECONDS, model_id)
    return model_id


def _unique_model_id(session, tenant_id, model_types, condition):
    stmt = select(ModelRecord.model_id).where(
        ModelRecord.tenant_id == tenant_id,
        ModelRecord.delete_flag == "N",
        condition,
    )
    if model_types:
        stmt = stmt.where(ModelRecord.model_type.in_(model_types))
    rows = session.execute(stmt.order_by(ModelRecord.model_id).limit(2)).all()
    if len(rows) != 1:
        return None
    return rows[0][0]
