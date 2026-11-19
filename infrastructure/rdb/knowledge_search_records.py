# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared read models for authorized knowledge search."""

from sqlalchemy import TIMESTAMP, BigInteger, Boolean, Column, Integer, Sequence, String, select

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from infrastructure.rdb.account_record import TenantGroupUser, UserTenant
from infrastructure.rdb.base import TableBase


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
        String(30), doc="In-group permission: EDIT, READ_ONLY, PRIVATE")
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


def read_knowledge_search_records(tenant_id: str, index_names: list[str]) -> list[dict]:
    if not index_names:
        return []
    from infrastructure.rdb.client import get_db_session

    record = KnowledgeRecord
    query = select(
        record.knowledge_id, record.index_name, record.knowledge_name, record.tenant_id,
        record.created_by, record.group_ids, record.ingroup_permission, record.knowledge_sources,
        record.embedding_model_id,
    ).where(
        record.tenant_id.in_((tenant_id, ASSET_OWNER_TENANT_ID)),
        record.index_name.in_(index_names),
        record.delete_flag != "Y",
    )
    with get_db_session() as session:
        return [dict(row) for row in session.execute(query).mappings()]


def read_knowledge_search_actor(user_id: str) -> tuple[dict | None, list[int]]:
    from infrastructure.rdb.client import get_db_session

    with get_db_session() as session:
        membership = session.execute(select(UserTenant.tenant_id, UserTenant.user_role).where(
            UserTenant.user_id == user_id, UserTenant.delete_flag == "N",
        )).mappings().first()
        groups = session.scalars(select(TenantGroupUser.group_id).where(
            TenantGroupUser.user_id == user_id, TenantGroupUser.delete_flag == "N",
        )).all()
        return dict(membership) if membership is not None else None, list(groups)
