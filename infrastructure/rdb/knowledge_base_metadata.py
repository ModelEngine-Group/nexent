# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Finite scoped legacy metadata mappings share the KB admission transaction."""

from dataclasses import replace

import sqlalchemy as sa
from contracts.knowledge import STORAGE_LEDGER_DATASET as LEDGER
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_CONVERSATIONS as CONVERSATIONS,
)
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_TAG_ASSIGNMENTS as TAGS,
)
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_TAG_PROJECTIONS as PROJECTIONS,
)
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_TOOL_BINDINGS as TOOLS,
)
from nexent.storage.errors import ScopeDenied

from infrastructure.rdb.account_record import UserTenant
from infrastructure.rdb.conversation_record import ConversationRecord
from infrastructure.rdb.knowledge_admission import admission_mapping
from infrastructure.rdb.mcp_execution_records import ToolInfo, ToolInstance
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.storage_ledger import ledger_catalog
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

tools, tool_info = ToolInstance.__table__, ToolInfo.__table__
conversations, memberships = ConversationRecord.__table__, UserTenant.__table__
metadata = sa.MetaData()


def _audit_columns():
    return [sa.Column('create_time', sa.DateTime, comment='Existing creation audit time'),
            sa.Column('update_time', sa.DateTime, comment='Existing last update audit time'),
            sa.Column('created_by', sa.String(100), comment='Existing creating actor'),
            sa.Column('updated_by', sa.String(100), comment='Existing updating actor'),
            sa.Column('delete_flag', sa.String(1), comment='Existing soft-delete marker')]


tags = sa.Table('resource_tag_assignment', metadata,
                sa.Column('assignment_id', sa.BigInteger, primary_key=True, comment='Existing tag binding identity'),
                sa.Column('tenant_id', sa.String(100), comment='Existing owning tenant'),
                sa.Column('resource_type', sa.String(50), comment='Existing tagged resource type'),
                sa.Column('resource_id', sa.String, comment='Existing canonical tagged resource identity'),
                *_audit_columns(), schema='nexent')
projections = sa.Table('document_tag_projection', metadata,
                       sa.Column('projection_id', sa.BigInteger, primary_key=True, comment='Existing projection ledger identity'),
                       sa.Column('tenant_id', sa.String(100), comment='Existing owning tenant'),
                       sa.Column('provider', sa.String(20), comment='Existing knowledge provider'),
                       sa.Column('knowledge_base_id', sa.String(255), comment='Existing provider KB identity'),
                       *_audit_columns(), schema='nexent')


def bind_base_metadata_records(scope, engine):
    tables, definitions, revisions, audits = admission_mapping()
    shared = ('create_time', 'update_time', 'created_by', 'updated_by', 'delete_flag')
    # The derived tenant field grants no global/system access to conversations.
    conversation_view = sa.select(*(conversations.c[name] for name in (
        'conversation_id', 'knowledge_scope', 'workbench_config', 'workbench_config_version', *shared,
    )), sa.literal(scope.tenant_id).label('tenant_id')).where(sa.exists(sa.select(1).where(
        memberships.c.user_id == conversations.c.created_by, memberships.c.tenant_id == scope.tenant_id,
        memberships.c.delete_flag == 'N',
    ))).subquery('scoped_knowledge_conversations')
    tool_view = sa.select(*(tools.c[name] for name in (
        'tool_instance_id', 'version_no', 'tenant_id', 'params', *shared,
    ))).where(tools.c.tool_id.in_(sa.select(tool_info.c.tool_id).where(
        tool_info.c.name == 'knowledge_base_search', tool_info.c.delete_flag == 'N',
    ))).subquery('scoped_knowledge_tool_bindings')
    additions = {TOOLS: tool_view, CONVERSATIONS: conversation_view, TAGS: tags, PROJECTIONS: projections}
    tables.update(additions)
    if LEDGER in scope.namespaces:
        definition, table, audit = ledger_catalog()
        tables[LEDGER] = table
        definitions.append(replace(definition, write_roles=frozenset()))
        revisions[LEDGER], audits[LEDGER] = 'version', audit
    if scope.system or scope.service_role != 'management' or not scope.namespaces <= tables.keys():
        raise ScopeDenied()
    for name, table in additions.items():
        definitions.append(DatasetDefinition(
            name, next(iter(table.primary_key)).name,
            tuple(FieldDefinition(c.name, 'integer' if isinstance(c.type, sa.Integer)
                                  else 'object' if isinstance(c.type, sa.JSON) else 'string', nullable=getattr(c, 'nullable', False))
                   for c in table.c), frozenset({'management'}), frozenset({'management'}),
            tenant_field='tenant_id', active_field=None if name == PROJECTIONS else 'delete_flag',
        ))
        revisions[name] = None
        audits[name] = RecordAudit('create_time', 'update_time', 'created_by', 'updated_by')
    return SQLRecordStore(scope, DatasetCatalog(tuple(definitions)),
                           {name: tables[name] for name in scope.namespaces}, engine,
                           revision_fields=revisions, audit_mappings=audits,
                           write_tables={name: table for name, table in {TOOLS: tools, CONVERSATIONS: conversations}.items()
                                         if name in scope.namespaces})
