# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    Column,
    Index,
    Integer,
    Sequence,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.sql import func

from infrastructure.rdb.base import SCHEMA, TableBase


class KnowledgeStorageObject(TableBase):
    """Durable ownership and accounting record for one KB source object."""

    __tablename__ = "knowledge_storage_object_t"
    __table_args__ = (
        CheckConstraint("version >= 0", name="ck_knowledge_storage_object_version"),
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
        comment="Storage object ledger ID",
    )
    create_time = Column(
        TIMESTAMP(timezone=False),
        nullable=False,
        server_default=func.now(),
        comment="Creation time",
    )
    update_time = Column(
        TIMESTAMP(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Update time",
    )
    delete_flag = Column(
        String(1),
        nullable=False,
        default="N",
        server_default=text("'N'"),
        comment="Whether it is deleted. Optional values: Y/N",
    )
    tenant_id = Column(String(100), nullable=False, comment="Tenant isolation key")
    knowledge_id = Column(
        BigInteger, nullable=False, comment="Owning knowledge base ID"
    )
    index_name = Column(
        String(100), nullable=False, comment="Owning Elasticsearch index name"
    )
    bucket_name = Column(String(255), nullable=False, comment="MinIO bucket name")
    object_name = Column(String(1024), nullable=False, comment="MinIO object name")
    raw_bytes = Column(
        BigInteger, nullable=False, comment="Authoritative MinIO object size in bytes"
    )
    status = Column(
        String(20),
        nullable=False,
        default="COMMITTED",
        server_default=text("'COMMITTED'"),
        comment="Accounting lifecycle status: COMMITTED or DELETED",
    )

    version = Column(
        Integer,
        nullable=False,
        server_default=text("0"),
        default=0,
        comment="Optimistic revision for StorageInterface ledger writes; legacy rows start at zero.",
    )
