# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Finite KB metadata mapping preserves the unchanged scheduler's local wall time."""

from datetime import UTC, datetime

import sqlalchemy as sa
from contracts.knowledge_deletion import DELETION_KNOWLEDGE_DATASET

from infrastructure.rdb.record_audit import RecordAudit, timestamp
from infrastructure.storage.catalog import DatasetDefinition, FieldDefinition


class _LocalWallTime(sa.TypeDecorator):
    """SI uses UTC instants; this existing database column uses process-local naive time."""

    impl = sa.DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return timestamp(value).astimezone().replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.astimezone(UTC)


knowledge = sa.Table(
    'knowledge_record_t', sa.MetaData(),
    sa.Column('knowledge_id', sa.BigInteger, primary_key=True, comment='Existing owning knowledge base ID'),
    sa.Column('tenant_id', sa.String(100), comment='Existing tenant isolation key'),
    sa.Column('index_name', sa.String(100), comment='Existing logical knowledge index name'),
    sa.Column('last_doc_update_time', _LocalWallTime(), comment='Existing local wall time used by the auto-summary scheduler'),
    sa.Column('create_time', sa.DateTime, comment='Existing creation audit time'),
    sa.Column('update_time', sa.DateTime, comment='Existing update audit time'),
    sa.Column('created_by', sa.String(100), comment='Existing creating actor'),
    sa.Column('updated_by', sa.String(100), comment='Existing last updating actor'),
    sa.Column('delete_flag', sa.String(1), comment='Existing soft-delete marker'),
    sa.Column('version', sa.Integer, nullable=False, server_default='0', comment='Revision for StorageInterface metadata updates'),
    sa.Column('deletion_request', sa.JSON, nullable=True, comment='Management-owned KB deletion admission snapshot'),
    sa.Column('embedding_model_id', sa.Integer),
    sa.Column('group_ids', sa.String),
    sa.Column('ingroup_permission', sa.String(30)),
    sa.Column('knowledge_sources', sa.String(300)),
    schema='nexent',
)


def metadata_catalog():
    names = ('knowledge_id', 'tenant_id', 'index_name', 'last_doc_update_time', 'create_time', 'update_time',
             'created_by', 'updated_by', 'delete_flag', 'version')
    definition = DatasetDefinition(
        DELETION_KNOWLEDGE_DATASET, 'knowledge_id',
        tuple(FieldDefinition(c.name, 'integer' if c.name in {'knowledge_id', 'version'} else 'string', nullable=c.nullable)
              for c in (knowledge.c[name] for name in names)),
        frozenset({'management'}), frozenset({'management'}), tenant_field='tenant_id', active_field='delete_flag',
    )
    return definition, knowledge, RecordAudit('create_time', 'update_time', 'created_by', 'updated_by',
                                             extra_dates=frozenset({'last_doc_update_time'}))
