# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Finite summary metadata and credential-free tenant-default model projections."""

import sqlalchemy as sa
from contracts.knowledge_summary import SUMMARY_DATASET, SUMMARY_MODEL_DATASET
from nexent.storage.errors import ScopeDenied

from infrastructure.rdb.knowledge_deletion_metadata import knowledge
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.tenant_config_record import TenantConfig
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)


def bind_summary_records(scope, engine):
    if scope.system or scope.service_role != 'management' or not scope.namespaces <= {SUMMARY_DATASET, SUMMARY_MODEL_DATASET}:
        raise ScopeDenied()
    names = ('knowledge_id', 'tenant_id', 'index_name', 'embedding_model_id', 'group_ids', 'ingroup_permission',
             'knowledge_sources', 'deletion_request', 'summary_frequency', 'last_summary_time', 'last_doc_update_time',
             'summary_schedule', 'knowledge_describe', 'version', 'create_time', 'update_time', 'created_by',
             'updated_by', 'delete_flag')
    definition = DatasetDefinition(SUMMARY_DATASET, 'knowledge_id', tuple(FieldDefinition(name,
        'integer' if name in {'knowledge_id', 'embedding_model_id', 'version'} else 'object'
        if name in {'summary_schedule', 'deletion_request'} else 'string', nullable=knowledge.c[name].nullable)
        for name in names), frozenset({'management'}), frozenset({'management'}), tenant_field='tenant_id', active_field='delete_flag')
    table = TenantConfig.__table__
    model = sa.select(table.c.tenant_config_id, table.c.tenant_id, table.c.config_value, table.c.delete_flag).where(
        table.c.config_key == 'LLM_ID').subquery(SUMMARY_MODEL_DATASET)
    model_definition = DatasetDefinition(SUMMARY_MODEL_DATASET, 'tenant_config_id', tuple(FieldDefinition(c.name,
        'integer' if c.name == 'tenant_config_id' else 'string', nullable=c.nullable) for c in model.c),
        frozenset({'management'}), tenant_field='tenant_id', active_field='delete_flag')
    definitions = {SUMMARY_DATASET: definition, SUMMARY_MODEL_DATASET: model_definition}
    tables = {SUMMARY_DATASET: knowledge, SUMMARY_MODEL_DATASET: model}
    return SQLRecordStore(scope, DatasetCatalog(tuple(definitions[name] for name in scope.namespaces)),
        {name: tables[name] for name in scope.namespaces}, engine,
        revision_fields={SUMMARY_DATASET: 'version'} if SUMMARY_DATASET in scope.namespaces else {},
        audit_mappings={SUMMARY_DATASET: RecordAudit('create_time', 'update_time', 'created_by', 'updated_by',
            extra_dates=frozenset({'last_summary_time', 'last_doc_update_time'}))} if SUMMARY_DATASET in scope.namespaces else {})
