# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only source/ledger projections are fixed to one selected KB before tenant scope."""

import sqlalchemy as sa
from contracts.knowledge_maintenance import INSPECTION_FILES, INSPECTION_LEDGER
from nexent.storage.errors import InvalidInput, ScopeDenied

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.knowledge_storage_record import KnowledgeStorageObject
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

files, ledger = KnowledgeFileLifecycle.__table__, KnowledgeStorageObject.__table__
FILE_FIELDS = ('file_id', 'tenant_id', 'knowledge_id', 'index_name', 'version', 'source_generation',
    'source_space', 'source_key', 'source_revision', 'source_sha256', 'source_upload_sha256',
    'bucket_name', 'object_name', 'local_source_path', 'storage_object_id', 'file_size', 'status',
    'deletion_request', 'ingestion_request', 'process_task_id', 'forward_task_id', 'parent_task_id', 'delete_flag')
LEDGER_FIELDS = ('storage_object_id', 'tenant_id', 'knowledge_id', 'index_name', 'bucket_name', 'object_name',
                 'raw_bytes', 'status', 'version', 'delete_flag')


def bind_source_inspection_records(scope, knowledge_id, engine):
    if type(knowledge_id) is not int or knowledge_id <= 0:
        raise InvalidInput()
    if scope.system or scope.service_role != 'management' or scope.namespaces != {INSPECTION_FILES, INSPECTION_LEDGER}:
        raise ScopeDenied()
    definitions, tables = [], {}
    for name, table, names, key in ((INSPECTION_FILES, files, FILE_FIELDS, 'file_id'),
                                   (INSPECTION_LEDGER, ledger, LEDGER_FIELDS, 'storage_object_id')):
        projection = sa.select(*(table.c[field] for field in names)).where(table.c.knowledge_id == knowledge_id).subquery(name)
        definitions.append(DatasetDefinition(name, key, tuple(FieldDefinition(field,
            'integer' if isinstance(table.c[field].type, sa.Integer) else 'object'
            if isinstance(table.c[field].type, sa.JSON) else 'string', nullable=table.c[field].nullable)
            for field in names), frozenset({'management'}), tenant_field='tenant_id',
            active_field='delete_flag' if name == INSPECTION_FILES else None))
        tables[name] = projection
    return SQLRecordStore(scope, DatasetCatalog(tuple(definitions)), tables, engine, revision_fields={})
