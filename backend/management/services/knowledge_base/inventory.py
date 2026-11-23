# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Assemble the existing list contract with SI directories and AgentOS metadata."""

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants import environment
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from contracts.knowledge_collections import (
    KnowledgeCollectionsDescribe,
    KnowledgeCollectionsDescribed,
)
from management.services.knowledge_base.inventory_records import KnowledgeListingReader
from management.services.knowledge_base.listing import prepare_indices_page
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def knowledge_listing_operation(context=None):
    owned = Event() if context is None else None
    context = context or OperationContext('knowledge-list-' + uuid4().hex, monotonic()+180, cancelled=owned)
    try:
        async with asyncio.timeout(context.remaining()):
            yield context
    except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
        if owned is not None:
            logger.warning('knowledge_list_timeout operation_id=%s phase=list budget_seconds=180 exception_type=%s',
                           context.operation_id, type(error).__name__)
        raise
    finally:
        if owned is not None:
            owned.set()


def _matches(name, pattern):
    if not name or name.startswith('.'):
        return False
    patterns = (pattern or '*').split(',')
    selected = patterns[0].startswith('-')
    for item in patterns:
        exclude = item.startswith('-')
        expression = item[1:] if exclude else item
        expression = '*' if expression == '_all' else expression
        if re.fullmatch(re.escape(expression).replace(r'\*', '.*').replace(r'\?', '.'), name):
            selected = not exclude
    return selected


def _stats(description):
    if description.statistics_error is not None:
        return {'error': description.statistics_error}
    value = description.statistics
    if value is None:
        raise Conflict()
    size = value.size_bytes
    for unit in ('B', 'KB', 'MB', 'GB', 'TB', 'PB'):
        if size < 1024 or unit == 'PB':
            formatted = f'{size:.2f} {unit}'
            break
        size /= 1024
    return {'base_info': {'doc_count': value.source_count, 'chunk_count': value.record_count, 'store_size': formatted,
        'process_source': value.process_source, 'embedding_model': value.embedding_model_name, 'embedding_dim': 1024,
        'creation_date': value.created_at_ms, 'update_date': value.created_at_ms},
        'search_performance': {'total_search_count': value.query_count, 'hit_count': value.cache_hit_count}}


class KnowledgeInventory:
    def __init__(self, *, reader=None, client=None):
        self.reader = reader or KnowledgeListingReader()
        self.client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)

    async def _blocking(self, name, action, *args, **kwargs):
        return await run_blocking('knowledge-list-'+name, action, *args, **kwargs,
                                  lane='control-io', owner='management.knowledge_base')

    async def _describe(self, actor, rows, view, statistics, context):
        result = {}
        for start in range(0, len(rows), 100):
            selected = rows[start:start+100]
            expected = {row['knowledge_id']: row['_metadata_revision'] for row in selected}
            if len(expected) != len(selected):
                raise Conflict()
            try:
                response = await self.client.describe_knowledge_collections(KnowledgeCollectionsDescribe(
                    knowledge_ids=list(expected), expected_revisions=expected, include_statistics=statistics, view=view,
                    native_documents=environment.KNOWLEDGE_RUNTIME_HYBRID_ENABLED),
                    actor.user_id, actor.tenant_id)
            except RuntimeUpstreamError as error:
                kind = {403: ScopeDenied, 409: Conflict, 504: DeadlineExceeded}.get(error.status_code)
                if kind is not None:
                    raise kind(operation_id=context.operation_id) from error
                raise
            if not isinstance(response, KnowledgeCollectionsDescribed):
                raise Conflict()
            if [r.knowledge_id for r in response.items] != list(expected) or any(
                r.expected_revision != expected[r.knowledge_id] for r in response.items):
                raise Conflict()
            result.update((r.knowledge_id, r) for r in response.items)
            context.remaining()
        return result

    async def visible(self, actor, tenant_id, *, pattern='*', ordered=False, view='resources', context):
        rows = await self._blocking('catalog', self.reader.snapshot, actor, tenant_id,
                                    ordered=ordered, view=view, context=context)
        rows = [row for row in rows if _matches(row['index_name'], pattern)]
        descriptions = await self._describe(actor, rows, view, False, context)
        return [row for row in rows if descriptions[row['knowledge_id']].present]

    async def list(self, actor, tenant_id, *, pattern='*', include_stats=False, pagination_enabled=False,
                   offset=0, limit=None, keyword=None, sources=None, models=None, inventory_read=False, context):
        view = 'inventory' if inventory_read else 'resources'
        rows = await self.visible(actor, tenant_id, pattern=pattern, ordered=pagination_enabled, view=view, context=context)
        rows, pagination = prepare_indices_page(rows, pagination_enabled, offset, limit, keyword, sources, models)
        indices = [row['index_name'] for row in rows]
        result = {'indices': indices, 'count': len(indices),
                  'index_permissions': {row['index_name']: row['permission'] for row in rows}}
        if pagination_enabled:
            result.update(pagination, estimated_row_height=112, estimated_item_heights=None)
        if include_stats:
            descriptions = await self._describe(actor, rows, view, True, context)
            if any(not r.present or r.model_display is None for r in descriptions.values()):
                raise Conflict()
            rows = await self._blocking('tags', self.reader.tags, actor, tenant_id, rows, context=context)
            infos = []
            for row in rows:
                description = descriptions[row['knowledge_id']]
                stats = _stats(description)
                infos.append({'knowledge_id': row['knowledge_id'], 'tags': row['tags'], 'name': row['index_name'],
                    'display_name': row.get('knowledge_name', row['index_name']), 'permission': row['permission'],
                    'group_ids': row['group_ids'], 'knowledge_sources': row['knowledge_sources'],
                    'ingroup_permission': row['ingroup_permission'], 'is_multimodal': description.model_display.is_multimodal,
                    'tenant_id': row['tenant_id'], 'embedding_model_name': description.model_display.display_name
                    or row.get('embedding_model_name', ''), 'embedding_model_id': row.get('embedding_model_id'),
                    'update_time': row.get('update_time'), 'summary_frequency': row.get('summary_frequency'),
                    'last_summary_time': row.get('last_summary_time'), 'preserve_source_file': row.get('preserve_source_file', True),
                    'stats': stats})
                if not inventory_read and row.get('embedding_model_name') is None:
                    await self._blocking('model-name', self.reader.backfill, actor, row,
                        stats.get('base_info', {}).get('embedding_model', ''), context=context)
            result['indices_info'] = infos
        return result


async def list_knowledge_indices(actor, tenant_id, *, context=None, reader=None, client=None, **kwargs):
    async with knowledge_listing_operation(context) as current:
        return await KnowledgeInventory(reader=reader, client=client).list(actor, tenant_id, context=current, **kwargs)


async def visible_knowledge_records(actor, *, context=None, reader=None, client=None):
    async with knowledge_listing_operation(context) as current:
        inventory = KnowledgeInventory(reader=reader, client=client)
        rows = []
        for tenant in dict.fromkeys((actor.tenant_id, ASSET_OWNER_TENANT_ID)):
            rows.extend(await inventory.visible(actor, tenant, context=current))
        return rows


async def resolve_listing_view(actor, request, *, context):
    targets = [value for value in request.query_params.getlist('tenant_id') if value] if request else []
    return await run_blocking('knowledge-list-view', KnowledgeListingReader().view, actor, targets,
        context=context, lane='control-io', owner='management.knowledge_base')
