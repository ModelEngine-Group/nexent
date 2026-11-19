# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read configuration and allocation totals without a KB-content visibility filter."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.knowledge import KEY_TENANT_HARD_LIMIT_BYTES
from contracts.roles import has_any_role
from management.services.knowledge_base.quota_authorization import (
    quota_identity_roles,
    require_quota_scope,
)
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

    def _authorize(self, identity, actor, tenant, context):
        roles = quota_identity_roles(identity, actor, context=context)
        if tenant != actor.tenant_id and not has_any_role(roles, {"SU", "ASSET_OWNER"}):
            raise ScopeDenied()

    def read(self, tenant, actor, *, context):
        context.remaining()
        with self.ports(actor, context=context) as (identity, open_records):
            self._authorize(identity, actor, tenant, context)
            records = open_records(tenant)
            require_quota_scope(records, actor, tenant)

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
