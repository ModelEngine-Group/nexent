# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Check exact tenant-local catalog names without creating a vector client."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import Comparison, OperationContext, PageRequest, RecordQuery

from infrastructure.knowledge_catalog import CATALOG, knowledge_catalog_ports

logger = logging.getLogger(__name__)
NAME_CHECK_SECONDS = 10


def name_status(name, actor, *, context, ports=knowledge_catalog_ports):
    context.remaining()
    with ports(actor, context=context) as records:
        scope = records.scope
        if (scope.service_role != 'management' or scope.tenant_id != actor.tenant_id
            or scope.actor_id != actor.user_id or scope.system or scope.resource_prefix):
            raise ScopeDenied()
        page = records.query(CATALOG, RecordQuery(fields=('knowledge_id',),
            where=Comparison('knowledge_name', 'eq', name)), PageRequest(limit=1), context=context)
        context.remaining()
        return {'status': 'exists_in_tenant' if page.items else 'available'}


async def check_knowledge_name(name, actor):
    cancelled = Event()
    context = OperationContext('knowledge-name-' + uuid4().hex, monotonic() + NAME_CHECK_SECONDS,
                               cancelled=cancelled)
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking('knowledge-name-check', name_status, name, actor, context=context,
                                      lane='control-io', owner='management.knowledge_base')
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('knowledge_name_check_timeout operation_id=%s phase=catalog threshold_seconds=%s error_type=%s',
                       context.operation_id, NAME_CHECK_SECONDS, type(error).__name__)
        raise
    finally:
        cancelled.set()
