# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persistent source identity and lifecycle shared by Management-owned file workflows."""

import sqlalchemy as sa
from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    Column,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.rdb.base import SCHEMA, TableBase


class KnowledgeFileLifecycle(TableBase):
    """Durable lifecycle record for one knowledge-base upload attempt."""

    __tablename__ = "knowledge_file_lifecycle_t"
    __table_args__ = (
        Index("idx_knowledge_file_local_source", "tenant_id", "knowledge_id", "local_source_path",
              postgresql_where=text("delete_flag = 'N' AND local_source_path IS NOT NULL")),
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
            postgresql_where=text("delete_flag = 'N' AND status = 'UPLOADING'"),
        ),
        Index(
            "idx_knowledge_source_reconcile",
            "upload_owner_service",
            "source_reconcile_after",
            "source_upload_started_at",
            postgresql_where=text(
                "delete_flag = 'N' AND status = 'UPLOADING' AND stage = 'SOURCE_UPLOAD'"
            ),
        ),
        Index(
            "idx_knowledge_source_finalize",
            "upload_owner_service", "source_upload_started_at", "source_reconcile_after",
            postgresql_where=text(
                "delete_flag = 'N' AND status = 'UPLOADING' AND stage IN ('SOURCE_UPLOAD', 'SOURCE_CONFIRMED', 'SOURCE_ACCOUNTED')"
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

    file_id = Column(
        String(64), primary_key=True, nullable=False, doc="Stable file lifecycle ID"
    )
    tenant_id = Column(String(100), nullable=False, doc="Tenant isolation key")
    knowledge_id = Column(BigInteger, nullable=False, doc="Owning knowledge base ID")
    index_name = Column(String(100), nullable=False, doc="Owning Elasticsearch index")
    bucket_name = Column(String(255), nullable=True, doc="MinIO bucket")
    object_name = Column(String(1024), nullable=True, doc="MinIO object name")
    local_source_path = Column(
        String(2048), nullable=True,
        comment="Management-owned local upload alias; never forwarded to Runtime.",
    )
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
    uploaded_at = Column(
        TIMESTAMP(timezone=False), nullable=True, doc="Successful MinIO upload time"
    )
    completed_at = Column(
        TIMESTAMP(timezone=False), nullable=True, doc="Successful ES indexing time"
    )
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
    processing_attempt = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    error_code = Column(
        String(100), nullable=True, doc="Error code reported by the ingestion flow"
    )
    error_message = Column(
        Text, nullable=True, doc="Raw failure summary when no error code exists"
    )
    error_stage = Column(String(30), nullable=True, doc="Failure stage")
    failed_at = Column(TIMESTAMP(timezone=False), nullable=True, doc="Failure time")
    deleted_at = Column(
        TIMESTAMP(timezone=False),
        nullable=True,
        doc="Time when the record reached DELETED status",
    )
    storage_object_id = Column(
        BigInteger, nullable=True, doc="Linked storage ledger ID"
    )
    version = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        doc="Optimistic-lock version",
    )

    source_upload_sha256 = Column(
        String(64),
        nullable=True,
        comment="Expected source SHA256 persisted before upload; null for legacy intents.",
    )
    source_upload_started_at = Column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="UTC start of the durable source upload intent, independent of legacy audit timezone.",
    )
    source_reconcile_after = Column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="UTC earliest next source reconciliation attempt; null means immediately eligible.",
    )
    source_generation = Column(
        Integer,
        nullable=False,
        server_default=text("0"),
        default=0,
        comment="Content generation independent of lifecycle CAS version; changes only with source replacement.",
    )
    source_space = Column(
        String(64),
        nullable=True,
        comment="Authorized logical source space; null until source is pinned.",
    )
    source_key = Column(
        String(1024),
        nullable=True,
        comment="Authorized logical source key; null until source is pinned.",
    )
    source_revision = Column(
        String(128),
        nullable=True,
        comment="Immutable source object revision; not a content checksum.",
    )
    source_sha256 = Column(
        String(64),
        nullable=True,
        comment="Independent SHA256 of source bytes; null until source is pinned.",
    )
    ingestion_request = Column(
        sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        nullable=True,
        comment="Validated Management ingestion intent snapshot, at most 16 KiB; NULL for legacy or unadmitted files.",
    )


_source = KnowledgeFileLifecycle.__table__.c
sa.CheckConstraint(
    sa.or_(
        _source.ingestion_request.is_(None),
        sa.and_(sa.func.jsonb_typeof(_source.ingestion_request) == "object",
                sa.func.octet_length(sa.cast(_source.ingestion_request, sa.Text)) <= 16384),
    ),
    name="ck_knowledge_ingestion_request", table=KnowledgeFileLifecycle.__table__,
).ddl_if(dialect="postgresql")
sa.Index(
    "idx_knowledge_ingestion_pending", _source.update_time, _source.file_id,
    postgresql_where=sa.and_(
        _source.delete_flag == "N", _source.ingestion_request.is_not(None),
        _source.status.in_(("UPLOADED", "PROCESSING", "FORWARDING")),
    ),
)
_source_fields = (
    _source.source_space,
    _source.source_key,
    _source.source_revision,
    _source.source_sha256,
)
sa.CheckConstraint(
    sa.and_(
        _source.source_generation >= 0,
        sa.or_(
            sa.and_(*(field.is_(None) for field in _source_fields)),
            sa.and_(
                *(field.is_not(None) for field in _source_fields),
                _source.source_space.regexp_match("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"),
                sa.func.length(_source.source_key) > 0,
                sa.func.length(_source.source_revision) > 0,
                _source.source_sha256.regexp_match("^[0-9a-f]{64}$"),
            ),
        ),
    ),
    name="ck_knowledge_file_cleanse_source",
    table=KnowledgeFileLifecycle.__table__,
)
sa.CheckConstraint(
    sa.and_(
        sa.or_(
            _source.source_upload_sha256.is_(None),
            _source.source_upload_sha256.regexp_match("^[0-9a-f]{64}$"),
        ),
        sa.or_(
            _source.stage.is_(None),
            _source.stage != "SOURCE_UPLOAD",
            sa.and_(
                _source.source_upload_sha256.is_not(None),
                _source.file_size.is_not(None),
                _source.file_size >= 0,
            ),
        ),
    ),
    name="ck_knowledge_source_upload_intent",
    table=KnowledgeFileLifecycle.__table__,
)
