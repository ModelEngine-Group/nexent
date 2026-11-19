# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped listing catalog, tenant configuration and original tag display join."""

from contextlib import contextmanager

import sqlalchemy as sa
from nexent.storage.models import StorageScope

from infrastructure.knowledge_catalog import knowledge
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.tenant_config_record import TenantConfig
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

CATALOG, CONFIG, TAGS = 'knowledge_list_catalog', 'knowledge_list_config', 'knowledge_list_tags'
tag_assignments = sa.Table('resource_tag_assignment', sa.MetaData(), sa.Column('assignment_id', sa.BigInteger, primary_key=True),
    sa.Column('tenant_id', sa.String(100)), sa.Column('definition_id', sa.BigInteger), sa.Column('value_id', sa.BigInteger),
    sa.Column('resource_type', sa.String(50)), sa.Column('resource_id', sa.String), sa.Column('delete_flag', sa.String(1)), schema='nexent')
tag_values = sa.Table('tag_value', sa.MetaData(), sa.Column('value_id', sa.BigInteger, primary_key=True),
    sa.Column('tenant_id', sa.String(100)), sa.Column('definition_id', sa.BigInteger), sa.Column('display_value', sa.String),
    sa.Column('delete_flag', sa.String(1)), schema='nexent')


def bind_listing_records(actor, tenant_id, engine):
    names = ('knowledge_id', 'tenant_id', 'index_name', 'knowledge_name', 'knowledge_describe', 'knowledge_sources',
        'embedding_model_id', 'embedding_model_name', 'group_ids', 'ingroup_permission', 'summary_frequency',
        'last_summary_time', 'preserve_source_file', 'version', 'create_time', 'update_time', 'created_by', 'updated_by', 'delete_flag')
    fields = tuple(FieldDefinition(name, 'integer' if name in {'knowledge_id', 'embedding_model_id', 'version'} else
        'boolean' if name == 'preserve_source_file' else 'string', nullable=knowledge.c[name].nullable) for name in names)
    catalog = DatasetDefinition(CATALOG, 'knowledge_id', fields, frozenset({'management'}), frozenset({'management'}),
                                tenant_field='tenant_id', active_field='delete_flag')
    config = TenantConfig.__table__
    config_names = ('tenant_config_id', 'tenant_id', 'config_key', 'config_value', 'delete_flag')
    config_def = DatasetDefinition(CONFIG, 'tenant_config_id', tuple(FieldDefinition(name,
        'integer' if name == 'tenant_config_id' else 'string', nullable=config.c[name].nullable) for name in config_names),
        frozenset({'management'}), tenant_field='tenant_id', active_field='delete_flag')
    assignment, value = tag_assignments, tag_values
    projection = sa.select(assignment.c.assignment_id, assignment.c.tenant_id, assignment.c.resource_type,
        assignment.c.resource_id, assignment.c.delete_flag, value.c.display_value).select_from(assignment.join(value,
        sa.and_(assignment.c.tenant_id == value.c.tenant_id, assignment.c.definition_id == value.c.definition_id,
                assignment.c.value_id == value.c.value_id))).subquery(TAGS)
    tag_def = DatasetDefinition(TAGS, 'assignment_id', tuple(FieldDefinition(c.name,
        'integer' if c.name == 'assignment_id' else 'string', nullable=True) for c in projection.c),
        frozenset({'management'}), tenant_field='tenant_id', active_field='delete_flag')
    return SQLRecordStore(StorageScope('management', tenant_id, actor.user_id, {CATALOG, CONFIG, TAGS}),
        DatasetCatalog((catalog, config_def, tag_def)), {CATALOG: knowledge, CONFIG: config, TAGS: projection}, engine,
        revision_fields={CATALOG: 'version'}, audit_mappings={CATALOG: RecordAudit('create_time', 'update_time',
            'created_by', 'updated_by', extra_dates=frozenset({'last_summary_time'}))})


@contextmanager
def knowledge_listing_ports(actor, tenant_id, *, context):
    engine, records = record_engine(context), None
    try:
        records = bind_listing_records(actor, tenant_id, engine)
        yield records
    finally:
        close_owned(context, ([records.close] if records is not None else []) + [engine.dispose])
