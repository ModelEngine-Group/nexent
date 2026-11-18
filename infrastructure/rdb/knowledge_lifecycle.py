# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fixed Runtime record powers for atomic chunk, file and collection lifecycle fences."""

from dataclasses import replace

import sqlalchemy as sa
from contracts.knowledge_base_deletion import BASE_DELETION_DATASET as BASE
from contracts.knowledge_chunk_mutation import CHANGES, STATES
from nexent.storage.errors import InvalidInput, ScopeDenied

from infrastructure.rdb.knowledge_base_deletions import deletions
from infrastructure.rdb.knowledge_chunk_mutations import changes, states
from infrastructure.rdb.knowledge_jobs import FILES, JOBS, files, jobs
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)


def bind_knowledge_lifecycle(scope, engine, *, mode, knowledge_ids=None):
    tables = {
        FILES: files,
        JOBS: jobs,
        BASE: deletions,
        CHANGES: changes,
        STATES: states,
    }
    writes = {
        "jobs": {FILES, JOBS, STATES},
        "mutation": {CHANGES, STATES, FILES},
        "deletion": {BASE, STATES},
        "read": set(),
    }
    if mode not in writes:
        raise InvalidInput()
    if (
        scope.system
        or scope.resource_prefix
        or scope.service_role != "runtime"
        or not scope.namespaces <= tables.keys()
    ):
        raise ScopeDenied()
    if mode == "read":
        if (not isinstance(knowledge_ids, tuple) or not 0 < len(knowledge_ids) <= 1000
            or any(type(value) is not int or value <= 0 for value in knowledge_ids)
            or len(set(knowledge_ids)) != len(knowledge_ids)):
            raise InvalidInput()
    elif knowledge_ids is not None:
        raise InvalidInput()
    scope = replace(scope, namespaces=frozenset(tables))
    definitions, audits = [], {}
    for name, table in tables.items():
        fields = tuple(
            FieldDefinition(
                column.name,
                "boolean"
                if isinstance(column.type, sa.Boolean)
                else "integer"
                if isinstance(column.type, sa.Integer)
                else "object"
                if isinstance(column.type, sa.JSON)
                else "string",
                nullable=column.nullable,
            )
            for column in table.c
        )
        definitions.append(
            DatasetDefinition(
                name,
                next(iter(table.primary_key.columns)).name,
                fields,
                frozenset({"runtime"}),
                frozenset({"runtime"}) if name in writes[mode] else frozenset(),
                tenant_field="tenant_id",
                active_field="delete_flag" if "delete_flag" in table.c else None,
            )
        )
        audits[name] = RecordAudit(
            "create_time",
            "update_time",
            "created_by",
            "updated_by",
            extra_dates=frozenset({"lease_until"}) if name == JOBS else frozenset(),
        )
    return SQLRecordStore(
        scope,
        DatasetCatalog(tuple(definitions)),
        {name: sa.select(table).where(table.c.knowledge_id.in_(knowledge_ids)).subquery(name) for name, table in tables.items()}
        if mode == "read" else tables,
        engine,
        revision_fields={name: "revision" for name in writes[mode]},
        audit_mappings=audits,
    )
