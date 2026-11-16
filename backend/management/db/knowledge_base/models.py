# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    text,
)


from sqlalchemy.sql import func


from management.db.base import SCHEMA, TableBase, _INGROUP_PERMISSION_DOC


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
