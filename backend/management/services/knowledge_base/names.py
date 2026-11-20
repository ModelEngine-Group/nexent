# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read exact tenant-local catalog names without creating a vector client."""

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


def _require_scope(records, actor):
    scope = records.scope
    if (scope.service_role != 'management' or scope.tenant_id != actor.tenant_id
        or scope.actor_id != actor.user_id or scope.system or scope.resource_prefix):
        raise ScopeDenied()


def name_status(name, actor, *, context, ports=knowledge_catalog_ports):
    context.remaining()
    with ports(actor, context=context) as records:
        _require_scope(records, actor)
        page = records.query(CATALOG, RecordQuery(fields=('knowledge_id',),
            where=Comparison('knowledge_name', 'eq', name)), PageRequest(limit=1), context=context)
        context.remaining()
        return {'status': 'exists_in_tenant' if page.items else 'available'}


def search_indices(names, actor, *, context, ports=knowledge_catalog_ports):
    context.remaining()
    distinct = list(dict.fromkeys(names))
    aliases = {}
    with ports(actor, context=context) as records:
        _require_scope(records, actor)
        for start in range(0, len(distinct), 1000):
            query = RecordQuery(fields=('knowledge_name', 'index_name'), where=Comparison(
                'knowledge_name', 'in', distinct[start:start + 1000],
            ))
            cursor = None
            while True:
                page = records.query(CATALOG, query, PageRequest(limit=1000, cursor=cursor), context=context)
                for row in page.items:
                    aliases.setdefault(row['knowledge_name'], row['index_name'])
                cursor = page.next_cursor
                if cursor is None:
                    break
    context.remaining()
    return [aliases.get(name, name) for name in names]


async def _read_name(operation, action, selection, actor):
    cancelled = Event()
    context = OperationContext(operation + '-' + uuid4().hex, monotonic() + NAME_CHECK_SECONDS,
                               cancelled=cancelled)
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking(operation, action, selection, actor, context=context,
                                      lane='control-io', owner='management.knowledge_base')
    except (TimeoutError, DeadlineExceeded) as error:
        logger.warning('knowledge_name_check_timeout operation_id=%s phase=%s threshold_seconds=%s error_type=%s',
                       context.operation_id, operation, NAME_CHECK_SECONDS, type(error).__name__)
        raise
    finally:
        cancelled.set()



async def check_knowledge_name(name, actor):
    return await _read_name('knowledge-name-check', name_status, name, actor)


async def resolve_search_index_names(names, actor):
    return await _read_name('knowledge-search-index-names', search_indices, names, actor)
