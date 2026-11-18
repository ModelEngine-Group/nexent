# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Expose only the configured tenant's DataMate URL through a read-only record port."""

from contextlib import contextmanager

from contracts.constants.constants import DATAMATE_URL
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope
from sqlalchemy import select

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.tenant_config_record import TenantConfig
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

DATASET = "datamate_configuration"
READER = "management.datamate.configuration"


def bind_datamate_configuration(scope, engine):
    if (
        scope.system
        or scope.service_role != "management"
        or scope.namespaces != {DATASET}
    ):
        raise ScopeDenied()
    table = TenantConfig.__table__
    projection = (
        select(table.c.tenant_config_id, table.c.tenant_id, table.c.config_value)
        .where(table.c.config_key == DATAMATE_URL, table.c.delete_flag == "N")
        .subquery(DATASET)
    )
    definition = DatasetDefinition(
        DATASET,
        "tenant_config_id",
        (
            FieldDefinition("tenant_config_id", "integer"),
            FieldDefinition("tenant_id", "string"),
            FieldDefinition("config_value", "string", nullable=True),
        ),
        frozenset({"management"}),
        tenant_field="tenant_id",
    )
    return SQLRecordStore(
        scope,
        DatasetCatalog((definition,)),
        {DATASET: projection},
        engine,
        revision_fields={},
    )


@contextmanager
def datamate_configuration_ports(tenant_id, *, context):
    # This technical reader is not an end-user authorization or an AgentOS principal.
    scope = StorageScope("management", tenant_id, READER, {DATASET})
    engine, records = record_engine(context), None
    try:
        records = bind_datamate_configuration(scope, engine)
        yield records
    finally:
        close_owned(
            context, ([records.close] if records is not None else []) + [engine.dispose]
        )
