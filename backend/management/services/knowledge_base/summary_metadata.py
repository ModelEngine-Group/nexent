# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read and edit stored summaries through scoped SI records and current DAC."""

import asyncio
import logging
from datetime import UTC, datetime
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.knowledge_summary import SUMMARY_DATASET, SUMMARY_MODEL_DATASET
from contracts.roles import has_any_role
from management.services.knowledge_base.collection_metadata_authorization import (
    metadata_identity,
    metadata_permission,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
    Revision,
    WriteOutcome,
)

from infrastructure.knowledge_collection_metadata import (
    METADATA,
    collection_metadata_ports,
)
from infrastructure.knowledge_summary import summary_ports

logger = logging.getLogger(__name__)


def summary_model_reference(records, context):
    page = records.query(
        SUMMARY_MODEL_DATASET, RecordQuery(), PageRequest(limit=2), context=context
    )
    if len(page.items) > 1 or page.next_cursor:
        raise Conflict()
    return page.items[0]["config_value"] if page.items else None


class SummaryMetadata:
    def __init__(self, *, ports=summary_ports, identities=collection_metadata_ports):
        self.ports, self.identities = ports, identities

    def _identity(self, actor, context):
        context.remaining()
        with self.identities(actor, context=context) as (identity, permissions, _):
            metadata_identity(
                identity, permissions, actor, "resources", context=context
            )

    def default_model(self, actor, *, context):
        self._identity(actor, context)
        with self.ports(
            actor.tenant_id, actor.user_id, context=context, models=True
        ) as (records, _):
            self._scope(records, actor.tenant_id, actor)
            value = summary_model_reference(records, context)
        self._identity(actor, context)
        return int(value) if value else None

    def _resolve(self, index_name, actor, target_tenant, *, edit, context):
        context.remaining()
        with self.identities(actor, context=context) as (
            identity,
            permissions,
            resources,
        ):
            _, roles, groups = metadata_identity(
                identity, permissions, actor, "resources", context=context
            )
            records = resources(cross_tenant=has_any_role(roles, {"SU"}))
            predicates = [Comparison("index_name", "eq", index_name)]
            if target_tenant is not None:
                predicates.append(Comparison("resource_tenant_id", "eq", target_tenant))
            page = records.query(
                METADATA,
                RecordQuery(where=Junction("and", tuple(predicates))),
                PageRequest(limit=2),
                context=context,
            )
            if not page.items:
                raise NotFound()
            if len(page.items) != 1 or page.next_cursor:
                raise ScopeDenied()
            row = {**page.items[0], "tenant_id": page.items[0]["resource_tenant_id"]}
            permission = metadata_permission(row, actor, roles, groups, "resources")
            if permission is None or edit and permission not in {"EDIT", "CREATOR"}:
                raise ScopeDenied()
            return row["knowledge_id"], row["tenant_id"]

    @staticmethod
    def _scope(records, tenant, actor):
        scope = records.scope
        if (
            scope.system
            or scope.resource_prefix
            or scope.service_role != "management"
            or scope.tenant_id != tenant
            or scope.actor_id != actor.user_id
        ):
            raise ScopeDenied()

    @staticmethod
    def _row(records, key, tenant, index_name, actor, context):
        SummaryMetadata._scope(records, tenant, actor)
        row = records.get(SUMMARY_DATASET, key, context=context)
        if row is None:
            raise NotFound()
        if (
            row["tenant_id"] != tenant
            or row["index_name"] != index_name
            or row.get("deletion_request") is not None
        ):
            raise ScopeDenied()
        return row

    def read(self, index_name, actor, *, target_tenant=None, context):
        key, tenant = self._resolve(
            index_name, actor, target_tenant, edit=False, context=context
        )
        with self.ports(tenant, actor.user_id, context=context) as (records, _):
            summary = self._row(records, key, tenant, index_name, actor, context)[
                "knowledge_describe"
            ]
        if self._resolve(
            index_name, actor, target_tenant, edit=False, context=context
        ) != (key, tenant):
            raise Conflict()
        context.remaining()
        return {
            "status": "success",
            "message": f"Index {index_name} summary retrieved successfully",
            "summary": summary,
        }

    def update(self, index_name, summary, actor, *, context):
        key, tenant = self._resolve(index_name, actor, None, edit=True, context=context)
        with (
            self.ports(tenant, actor.user_id, context=context) as (records, _),
            records.transaction(context=context) as tx,
        ):
            row = self._row(tx, key, tenant, index_name, actor, context)
            result = tx.patch(
                SUMMARY_DATASET,
                key,
                FieldPatch(
                    set_values={
                        "knowledge_describe": summary,
                        "last_summary_time": datetime.now(UTC).isoformat(),
                    }
                ),
                expected=Revision(str(row["version"])),
                context=context,
            )
            if result.outcome == WriteOutcome.UNKNOWN:
                raise OutcomeUnknown(operation_id=context.operation_id)
            if result.outcome != WriteOutcome.CONFIRMED or not result.matched:
                raise Conflict()
            if self._resolve(index_name, actor, None, edit=True, context=context) != (
                key,
                tenant,
            ):
                raise Conflict()
            context.remaining()
        return {
            "status": "success",
            "message": f"Index {index_name} summary updated successfully",
            "summary": summary,
        }


async def run_summary_metadata(operation, function, *, context=None):
    stop = Event() if context is None else None
    context = context or OperationContext(
        "knowledge-summary-" + operation + "-" + uuid4().hex,
        monotonic() + 30,
        cancelled=stop,
    )
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking(
                "knowledge-summary-" + operation,
                lambda: function(context),
                lane="control-io",
                owner="management.knowledge.summary",
            )
    except (TimeoutError, DeadlineExceeded) as error:
        if stop is not None:
            logger.warning(
                "knowledge_summary_metadata_timeout operation_id=%s phase=%s budget_seconds=30 exception_type=%s",
                context.operation_id,
                operation,
                type(error).__name__,
            )
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        if stop is not None:
            stop.set()


async def read_summary(index_name, actor, *, target_tenant=None, context=None):
    return await run_summary_metadata(
        "read",
        lambda ctx: SummaryMetadata().read(
            index_name, actor, target_tenant=target_tenant, context=ctx
        ),
        context=context,
    )


async def read_default_summary_model(actor, *, context=None):
    return await run_summary_metadata(
        "default-model",
        lambda ctx: SummaryMetadata().default_model(actor, context=ctx),
        context=context,
    )


async def update_summary(index_name, summary, actor, *, context=None):
    return await run_summary_metadata(
        "update",
        lambda ctx: SummaryMetadata().update(index_name, summary, actor, context=ctx),
        context=context,
    )
