# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
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


from sqlalchemy.sql import func


from management.db.base import SCHEMA, TableBase


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


class MemoryRecord(TableBase):
    """Internal memory records persisted in PostgreSQL.

    This is the authoritative store for agent short-term memory, which
    additionally mirrors the content into Elasticsearch (managed by
    ``management.services.memory.index``).

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
