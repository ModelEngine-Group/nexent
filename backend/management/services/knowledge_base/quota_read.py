# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read configuration and allocation totals without a KB-content visibility filter."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.knowledge import KEY_TENANT_HARD_LIMIT_BYTES
from contracts.roles import has_any_role, roles_from_record
from management.services.knowledge_base.quota_rules import (
    allocation_summary,
    hard_limit_values,
    warning_values,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import Comparison, OperationContext, PageRequest, RecordQuery

from infrastructure.tenant_quota_read import CATALOG, CONFIGS, tenant_quota_read_ports

logger = logging.getLogger(__name__)


class TenantQuotaReader:
    def __init__(self, *, ports=tenant_quota_read_ports):
        self.ports = ports

    @staticmethod
    def _scope(port, actor, tenant):
        scope = port.scope
        if (
            scope.service_role != "management"
            or scope.system
            or scope.resource_prefix
            or scope.tenant_id != tenant
            or scope.actor_id != actor.user_id
        ):
            raise ScopeDenied()

    def _authorize(self, identity, actor, tenant, context):
        self._scope(identity, actor, actor.tenant_id)
        rows = []
        for dataset in ("cleanse_memberships", "cleanse_accounts"):
            page = identity.query(
                dataset,
                RecordQuery(where=Comparison("user_id", "eq", actor.user_id)),
                PageRequest(limit=2),
                context=context,
            )
            if len(page.items) != 1 or page.next_cursor:
                raise ScopeDenied()
            rows.append(page.items[0])
        member, account = rows
        if member.get("tenant_id") != actor.tenant_id:
            raise ScopeDenied()
        try:
            roles = roles_from_record(account)
        except ValueError as error:
            raise ScopeDenied() from error
        if tenant != actor.tenant_id and not has_any_role(roles, {"SU", "ASSET_OWNER"}):
            raise ScopeDenied()

    def read(self, tenant, actor, *, context):
        context.remaining()
        with self.ports(actor, context=context) as (identity, open_records):
            self._authorize(identity, actor, tenant, context)
            records = open_records(tenant)
            self._scope(records, actor, tenant)

            def config(key):
                page = records.query(
                    CONFIGS,
                    RecordQuery(where=Comparison("config_key", "eq", key)),
                    PageRequest(limit=1),
                    context=context,
                )
                return page.items[0]["config_value"] if page.items else None

            hard = hard_limit_values(
                config(KEY_TENANT_HARD_LIMIT_BYTES),
                config("KB_QUOTA_HARD_LIMIT_EDITABLE"),
            )
            warning = warning_values(
                config("KB_QUOTA_WARNING_ENABLED"),
                config("KB_QUOTA_WARNING_THRESHOLD_PCT"),
                config("KB_QUOTA_CRITICAL_THRESHOLD_PCT"),
            )
            # Original summary includes all non-deleted tenant KBs, including
            # private resources belonging to others and non-ES providers.
            query = RecordQuery(where=Comparison("delete_flag", "ne", "Y"))
            count = records.count(CATALOG, query, context=context)
            allocated = records.sum(
                CATALOG, "quota_limit_bytes", query, context=context
            )
            from nexent.storage.models import Junction

            finite = records.count(
                CATALOG,
                RecordQuery(
                    where=Junction(
                        "and",
                        (
                            Comparison("delete_flag", "ne", "Y"),
                            Comparison("quota_limit_bytes", "is_null", False),
                        ),
                    )
                ),
                context=context,
            )
            self._authorize(identity, actor, tenant, context)
            context.remaining()
            return {
                **hard,
                **warning,
                "summary": allocation_summary(hard, allocated, count, finite),
            }


async def read_tenant_quota(tenant, actor):
    cancelled = Event()
    context = OperationContext(
        "tenant-quota-read-" + uuid4().hex, monotonic() + 10, cancelled=cancelled
    )
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking(
                "tenant-quota-read",
                TenantQuotaReader().read,
                tenant,
                actor,
                context=context,
                lane="control-io",
                owner="management.knowledge_base",
            )
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning(
            "tenant_quota_read_timeout operation_id=%s phase=metadata threshold_seconds=10 exception_type=%s",
            context.operation_id,
            type(error).__name__,
        )
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        cancelled.set()
