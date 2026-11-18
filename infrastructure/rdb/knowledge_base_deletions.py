# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime owns collection deletion receipts and reads only its own writer barriers."""

from typing import ClassVar

import sqlalchemy as sa

from infrastructure.rdb.base import TableBase


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
    from infrastructure.rdb.knowledge_lifecycle import bind_knowledge_lifecycle

    return bind_knowledge_lifecycle(scope, engine, mode="deletion")
