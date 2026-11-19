# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Finite read-only catalog, source-ledger and configuration handles for admission."""

from contextlib import contextmanager
from dataclasses import replace

from contracts.knowledge import STORAGE_LEDGER_DATASET
from nexent.storage.models import StorageScope

from infrastructure.knowledge_catalog import bind_knowledge_catalog
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.storage_ledger import ledger_catalog
from infrastructure.rdb.tenant_config_record import TenantConfig
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

CONFIGS = 'knowledge_quota_configs'


def bind_document_quota(actor, engine):
    owned = []
    try:
        owned.append(bind_knowledge_catalog(actor, engine))
        definition, table, audit = ledger_catalog()
        owned.append(SQLRecordStore(StorageScope('management', actor.tenant_id, actor.user_id, {STORAGE_LEDGER_DATASET}),
            DatasetCatalog((replace(definition, write_roles=frozenset()),)), {STORAGE_LEDGER_DATASET: table}, engine,
            revision_fields={}, audit_mappings={STORAGE_LEDGER_DATASET: audit}))
        table = TenantConfig.__table__
        names = ('tenant_config_id', 'tenant_id', 'config_key', 'config_value', 'delete_flag')
        definition = DatasetDefinition(CONFIGS, 'tenant_config_id', tuple(FieldDefinition(name,
            'integer' if name == 'tenant_config_id' else 'string', nullable=table.c[name].nullable) for name in names),
            frozenset({'management'}), tenant_field='tenant_id', active_field='delete_flag')
        owned.append(SQLRecordStore(StorageScope('management', actor.tenant_id, actor.user_id, {CONFIGS}),
            DatasetCatalog((definition,)), {CONFIGS: table}, engine, revision_fields={}))
        return tuple(owned)
    except BaseException:
        for port in reversed(owned):
            port.close()
        raise


@contextmanager
def document_quota_ports(actor, *, context):
    engine, owned = record_engine(context), ()
    try:
        owned = bind_document_quota(actor, engine)
        yield owned
    finally:
        close_owned(context, [port.close for port in reversed(owned)] + [engine.dispose])
