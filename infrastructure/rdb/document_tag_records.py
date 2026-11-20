# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only file tag views, with the original tenant joins and display ordering."""

import sqlalchemy as sa
from nexent.storage.models import StorageScope

from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

KNOWLEDGE, BINDINGS, ASSIGNMENTS = (
    "document_tag_knowledge",
    "document_tag_bindings",
    "document_tag_assignments",
)


def _table(name, primary, names):
    integer = {
        "knowledge_id",
        "bucket_id",
        "bucket_resource_type_id",
        "definition_id",
        "value_id",
        "assignment_id",
        "projection_id",
        "sort_order",
    }
    return sa.Table(
        name,
        sa.MetaData(),
        *(
            sa.Column(
                field,
                sa.BigInteger if field in integer else sa.String,
                primary_key=field == primary,
            )
            for field in names
        ),
        schema="nexent",
    )


TABLES = {
    "knowledge": _table(
        "knowledge_record_t",
        "knowledge_id",
        ("knowledge_id", "tenant_id", "index_name", "delete_flag"),
    ),
    "bucket": _table(
        "tag_bucket",
        "bucket_id",
        ("bucket_id", "tenant_id", "bucket_key", "status", "delete_flag"),
    ),
    "binding": _table(
        "tag_bucket_resource_type",
        "bucket_resource_type_id",
        (
            "bucket_resource_type_id",
            "tenant_id",
            "bucket_id",
            "resource_type",
            "status",
            "delete_flag",
        ),
    ),
    "definition": _table(
        "tag_definition",
        "definition_id",
        (
            "definition_id",
            "tenant_id",
            "definition_key",
            "definition_name",
            "selection_mode",
            "sort_order",
            "status",
            "delete_flag",
        ),
    ),
    "value": _table(
        "tag_value",
        "value_id",
        (
            "value_id",
            "tenant_id",
            "definition_id",
            "display_value",
            "status",
            "sort_order",
            "delete_flag",
        ),
    ),
    "assignment": _table(
        "resource_tag_assignment",
        "assignment_id",
        (
            "assignment_id",
            "tenant_id",
            "definition_id",
            "value_id",
            "resource_type",
            "resource_id",
            "delete_flag",
        ),
    ),
}


def bind_document_tag_records(actor, engine):
    knowledge, bucket, binding, definition, value, assignment = (
        TABLES[name]
        for name in (
            "knowledge",
            "bucket",
            "binding",
            "definition",
            "value",
            "assignment",
        )
    )
    bindings = (
        sa.select(
            binding.c.bucket_resource_type_id,
            binding.c.tenant_id,
            binding.c.resource_type,
            binding.c.delete_flag,
            bucket.c.bucket_key,
        )
        .select_from(
            binding.join(
                bucket,
                sa.and_(
                    binding.c.tenant_id == bucket.c.tenant_id,
                    binding.c.bucket_id == bucket.c.bucket_id,
                ),
            )
        )
        .where(
            binding.c.status == "active",
            bucket.c.status == "active",
            bucket.c.delete_flag == "N",
        )
        .subquery(BINDINGS)
    )
    # Deleted/disabled definitions and values remain visible in existing display
    # assignments. Only the assignment's soft-delete flag is an active filter.
    assignments = (
        sa.select(
            assignment.c.assignment_id,
            assignment.c.tenant_id,
            assignment.c.resource_type,
            assignment.c.resource_id,
            assignment.c.delete_flag,
            definition.c.definition_id,
            definition.c.definition_key,
            definition.c.definition_name,
            definition.c.selection_mode,
            definition.c.sort_order.label("definition_order"),
            value.c.value_id,
            value.c.display_value,
            value.c.status.label("value_status"),
            value.c.sort_order.label("value_order"),
        )
        .select_from(
            assignment.join(
                definition,
                sa.and_(
                    assignment.c.tenant_id == definition.c.tenant_id,
                    assignment.c.definition_id == definition.c.definition_id,
                ),
            ).join(
                value,
                sa.and_(
                    assignment.c.tenant_id == value.c.tenant_id,
                    assignment.c.definition_id == value.c.definition_id,
                    assignment.c.value_id == value.c.value_id,
                ),
            )
        )
        .subquery(ASSIGNMENTS)
    )
    tables = {KNOWLEDGE: knowledge, BINDINGS: bindings, ASSIGNMENTS: assignments}
    definitions = tuple(
        DatasetDefinition(
            name,
            primary,
            tuple(
                FieldDefinition(
                    column.name,
                    "integer" if isinstance(column.type, sa.Integer) else "string",
                    nullable=True,
                )
                for column in table.c
            ),
            frozenset({"management"}),
            tenant_field="tenant_id",
            active_field="delete_flag",
        )
        for name, primary, table in (
            (KNOWLEDGE, "knowledge_id", knowledge),
            (BINDINGS, "bucket_resource_type_id", bindings),
            (ASSIGNMENTS, "assignment_id", assignments),
        )
    )
    return SQLRecordStore(
        StorageScope("management", actor.tenant_id, actor.user_id, frozenset(tables)),
        DatasetCatalog(definitions),
        tables,
        engine,
        revision_fields={},
    )
