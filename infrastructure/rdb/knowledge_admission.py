# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One scoped transaction domain for KB admission and preallocated upload files."""

import sqlalchemy as sa
from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from nexent.storage.errors import ScopeDenied

from infrastructure.rdb.knowledge_deletion_metadata import knowledge
from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

files = KnowledgeFileLifecycle.__table__


def bind_admission_records(scope, engine):
    tables = {KB: knowledge, FILES: files}
    if scope.system or scope.service_role != 'management' or not scope.namespaces <= tables.keys():
        raise ScopeDenied()
    names = {KB: ('knowledge_id', 'tenant_id', 'index_name', 'version', 'deletion_request', 'create_time',
                  'update_time', 'created_by', 'updated_by', 'delete_flag'), FILES: tuple(c.name for c in files.c)}
    definitions = []
    for name in tables:
        definitions.append(DatasetDefinition(
            name, 'knowledge_id' if name == KB else 'file_id',
            tuple(FieldDefinition(field,
                                  'integer' if isinstance(tables[name].c[field].type, sa.Integer)
                                  else 'object' if isinstance(tables[name].c[field].type, sa.JSON)
                                  else 'string', nullable=tables[name].c[field].nullable)
                  for field in names[name]),
            frozenset({'management'}), frozenset({'management'}), tenant_field='tenant_id', active_field='delete_flag',
        ))
    return SQLRecordStore(scope, DatasetCatalog(tuple(definitions)),
                          {name: tables[name] for name in scope.namespaces}, engine,
                          revision_fields={KB: 'version', FILES: 'version'},
                          audit_mappings={name: RecordAudit(
                              'create_time', 'update_time', 'created_by', 'updated_by',
                              extra_dates=frozenset(c.name for c in tables[name].c
                                                    if isinstance(c.type, sa.DateTime) and c.name not in {'create_time', 'update_time'})
                          ) for name in tables})
