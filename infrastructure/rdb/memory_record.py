# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PostgreSQL mapping for short-term and legacy Memory records."""

from sqlalchemy import Column, Index, Integer, String, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import ARRAY

from infrastructure.rdb.base import SCHEMA, TableBase


class MemoryRecord(TableBase):
    """Internal memory records persisted in PostgreSQL.

    This is the authoritative store for agent short-term memory, which
    additionally mirrors the content into Elasticsearch.

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
