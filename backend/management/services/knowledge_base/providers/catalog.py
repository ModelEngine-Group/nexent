# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own DataMate directory policy while every database operation uses RecordStore."""

from dataclasses import replace
from time import monotonic
from uuid import uuid4

from management.services.knowledge_base.catalog_policy import enforce_catalog_creation
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    OperationContext,
    PageRequest,
    RecordQuery,
    Revision,
    Sort,
    WriteOutcome,
)

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_catalog import CATALOG, knowledge_catalog_ports


def _operation(context):
    context = context or OperationContext(
        "datamate-catalog-" + uuid4().hex, monotonic() + 10
    )
    context = replace(context, deadline=min(context.deadline, monotonic() + 10))
    context.remaining()
    return context


def _selected(records, index_name, context):
    page = records.query(
        CATALOG,
        RecordQuery(where=Comparison("index_name", "eq", index_name)),
        PageRequest(limit=2),
        context=context,
    )
    if len(page.items) > 1 or getattr(page, "next_cursor", None):
        raise Conflict()
    row = page.items[0] if page.items else None
    if row is not None and (
        row["knowledge_sources"] != "datamate" or row["deletion_request"] is not None
    ):
        raise ScopeDenied()
    return row


def _confirmed(receipt, context, *, deleted=False):
    if receipt.outcome is WriteOutcome.UNKNOWN:
        raise OutcomeUnknown(operation_id=context.operation_id)
    if receipt.outcome is not WriteOutcome.CONFIRMED or not (
        receipt.deleted if deleted else receipt.matched
    ):
        raise Conflict()


def upsert_datamate_record(data, *, ports=knowledge_catalog_ports, context=None):
    context = _operation(context)
    actor = ServicePrincipal(data["user_id"], data["tenant_id"])
    name = data.get("knowledge_name") or data["index_name"]
    with ports(
        actor, context=context, writable=True, knowledge_name=name.strip()
    ) as records, records.transaction(context=context) as tx:
        current = _selected(tx, data["index_name"], context)
        values = {
            "knowledge_name": name,
            "knowledge_describe": data.get("knowledge_describe", ""),
            "knowledge_sources": "datamate",
            "embedding_model_name": data.get("embedding_model_name"),
            "embedding_model_id": data.get("embedding_model_id"),
        }
        if current is None:
            values["knowledge_name"] = name.strip()
            enforce_catalog_creation(tx, actor, values["knowledge_name"], context)
            row = tx.create(
                CATALOG,
                {
                    **values,
                    "index_name": data["index_name"],
                    "preserve_source_file": True,
                },
                context=context,
            )
        else:
            receipt = tx.patch(
                CATALOG,
                current["knowledge_id"],
                FieldPatch(set_values=values),
                expected=Revision(str(current["version"])),
                context=context,
            )
            _confirmed(receipt, context)
            row = {**current, **values}
        return {
            key: row[key]
            for key in ("knowledge_id", "index_name", "knowledge_name")
        }


def list_datamate_records(
    tenant_id, user_id, *, ports=knowledge_catalog_ports, context=None
):
    context = _operation(context)
    actor = ServicePrincipal(user_id, tenant_id)
    with ports(actor, context=context) as records:
        result, cursor, seen = [], None, set()
        while True:
            page = records.query(
                CATALOG,
                RecordQuery(
                    where=Comparison("knowledge_sources", "eq", "datamate"),
                    order_by=(Sort("knowledge_id"),),
                ),
                PageRequest(limit=500, cursor=cursor),
                context=context,
            )
            result.extend(page.items)
            if page.next_cursor is None:
                return result
            if page.next_cursor in seen:
                raise Conflict()
            seen.add(page.next_cursor)
            cursor = page.next_cursor


def delete_datamate_record(data, *, ports=knowledge_catalog_ports, context=None):
    context = _operation(context)
    actor = ServicePrincipal(data["user_id"], data["tenant_id"])
    with (
        ports(actor, context=context, writable=True) as records,
        records.transaction(context=context) as tx,
    ):
        current = _selected(tx, data["index_name"], context)
        if current is None:
            return False
        receipt = tx.delete(
            CATALOG,
            current["knowledge_id"],
            expected=Revision(str(current["version"])),
            context=context,
        )
        _confirmed(receipt, context, deleted=True)
        return True
