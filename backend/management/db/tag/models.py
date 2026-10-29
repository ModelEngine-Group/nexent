# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    Column,
    Computed,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)


from sqlalchemy.dialects.postgresql import JSONB


from management.db.base import SCHEMA, TableBase, _TENANT_ID_DOC


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
