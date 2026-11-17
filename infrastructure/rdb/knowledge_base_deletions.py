# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime owns collection deletion receipts and reads only its own writer barriers."""

from typing import ClassVar

import sqlalchemy as sa
from contracts.knowledge_base_deletion import BASE_DELETION_DATASET as BASE
from contracts.knowledge_base_deletion import RUNTIME_FILES as FILES
from contracts.knowledge_base_deletion import RUNTIME_JOBS as JOBS
from nexent.storage.errors import ScopeDenied

from infrastructure.rdb.base import TableBase
from infrastructure.rdb.knowledge_jobs import files, jobs
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)


class RuntimeKnowledgeBaseDeletion(TableBase):
    __tablename__ = 'runtime_knowledge_base_deletion_t'
    __table_args__: ClassVar[dict] = {'schema': 'nexent'}
    job_id = sa.Column(sa.String(32), primary_key=True, comment='Stable UUID for one actor-scoped KB deletion request.')
    tenant_id = sa.Column(sa.String(100), nullable=False, comment='Tenant owning the exclusive collection.')
    user_id = sa.Column(sa.String(100), nullable=False, comment='Original authorized KB deletion actor.')
    knowledge_id = sa.Column(sa.Integer, nullable=False, comment='Management knowledge resource reference.')
    collection = sa.Column(sa.String(100), nullable=False, comment='Authorized logical collection; never a physical index name.')
    status = sa.Column(sa.String(30), nullable=False, comment='Deleting reserves one write; deleted confirms physical absence.')
    revision = sa.Column(sa.Integer, nullable=False, comment='StorageInterface optimistic revision.')


deletions = RuntimeKnowledgeBaseDeletion.__table__
for name, comment in {
    'create_time': 'UTC time deletion ownership was reserved.',
    'update_time': 'UTC time of the latest cleanup observation.',
    'created_by': 'Trusted actor reserving collection deletion.',
    'updated_by': 'Trusted actor confirming collection cleanup.',
    'delete_flag': 'Soft deletion marker; active deletion receipts remain N.',
}.items():
    deletions.c[name].comment = comment
    deletions.c[name].nullable = False
sa.CheckConstraint("revision > 0 AND knowledge_id > 0 AND status IN ('deleting', 'deleted')",
                   name='ck_runtime_kb_deletion_state', table=deletions)


def bind_base_deletion_records(scope, engine):
    tables = {BASE: deletions, JOBS: jobs, FILES: files}
    if scope.system or scope.service_role != 'runtime' or not scope.namespaces <= tables.keys():
        raise ScopeDenied()
    names = {
        BASE: tuple(c.name for c in deletions.c),
        JOBS: ('job_id', 'tenant_id', 'knowledge_id', 'writer_ended', 'delete_flag'),
        FILES: ('record_id', 'tenant_id', 'knowledge_id', 'latest_version', 'tombstone_version',
                'active_job_id', 'visible_job_id', 'visible_version', 'visible_generation', 'delete_flag'),
    }
    definitions = []
    for name, table in tables.items():
        definitions.append(DatasetDefinition(
            name, next(iter(table.primary_key.columns)).name,
            tuple(FieldDefinition(field, 'integer' if isinstance(table.c[field].type, sa.Integer)
                                  else 'boolean' if isinstance(table.c[field].type, sa.Boolean) else 'string',
                                  nullable=table.c[field].nullable) for field in names[name]),
            frozenset({'runtime'}), frozenset({'runtime'}) if name == BASE else frozenset(),
            tenant_field='tenant_id', active_field='delete_flag',
        ))
    return SQLRecordStore(scope, DatasetCatalog(tuple(definitions)),
                          {name: tables[name] for name in scope.namespaces}, engine,
                          revision_fields={BASE: 'revision'},
                          audit_mappings={BASE: RecordAudit('create_time', 'update_time', 'created_by', 'updated_by')})
