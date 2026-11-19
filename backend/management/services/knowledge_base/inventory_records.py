# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read authorized list rows and display projections through StorageInterface."""

import logging

from contracts.constants.constants import ASSET_OWNER_TENANT_ID, DEFAULT_GROUP_ID
from contracts.roles import has_any_role
from management.services.knowledge_base.collection_metadata_authorization import (
    metadata_identity,
    metadata_permission,
)
from management.utils.serialization import convert_string_to_list
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
)
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    PageRequest,
    RecordQuery,
    Revision,
    Sort,
    WriteOutcome,
)

from infrastructure.knowledge_collection_metadata import collection_metadata_ports
from infrastructure.knowledge_listing import (
    CATALOG,
    CONFIG,
    TAGS,
    knowledge_listing_ports,
)
from infrastructure.knowledge_search import knowledge_search_revision

logger = logging.getLogger(__name__)


def _scope(records, actor, tenant):
    scope = records.scope
    if (scope.system or scope.resource_prefix or scope.service_role != 'management'
        or scope.actor_id != actor.user_id or scope.tenant_id != tenant):
        raise ScopeDenied()


def _pages(records, dataset, query, context):
    cursor, seen = None, set()
    while True:
        page = records.query(dataset, query, PageRequest(limit=500, cursor=cursor), context=context)
        yield from page.items
        if page.next_cursor is None:
            return
        if page.next_cursor in seen:
            raise Conflict()
        seen.add(page.next_cursor); cursor = page.next_cursor


def _default_group(records, context):
    try:
        page = records.query(CONFIG, RecordQuery(where=Comparison('config_key', 'eq', DEFAULT_GROUP_ID)),
                             PageRequest(limit=2), context=context)
        if len(page.items) > 1 or page.next_cursor:
            raise Conflict()
        raw = page.items[0]['config_value'] if page.items else None
        return int(raw) if raw else None
    except (DeadlineExceeded, OperationCancelled, ScopeDenied):
        raise
    except Exception as error:  # noqa: BLE001 - Preserve the old display-only group lookup.
        logger.warning('knowledge_list_default_group_unavailable operation_id=%s exception_type=%s',
                       context.operation_id, type(error).__name__)
        return None


class KnowledgeListingReader:
    def __init__(self, *, ports=knowledge_listing_ports, identities=collection_metadata_ports):
        self.ports, self.identities = ports, identities

    def view(self, actor, targets, *, context):
        with self.identities(actor, context=context) as (identity, permissions, _):
            _, roles, _ = metadata_identity(identity, permissions, actor, 'resources', context=context)
            if has_any_role(roles, {'ADMIN', 'SU'}) or len(roles) > 1 and not targets:
                return 'resources'
            try:
                metadata_identity(identity, permissions, actor, 'inventory', context=context)
            except ScopeDenied:
                return 'resources'
            if any(target != actor.tenant_id for target in targets):
                raise ScopeDenied()
            return 'inventory'

    def snapshot(self, actor, tenant_id, *, view, ordered, context):
        context.remaining()
        with self.identities(actor, context=context) as (identity, permissions, _):
            _, roles, groups = metadata_identity(identity, permissions, actor, view, context=context)
        if (view == 'inventory' and tenant_id != actor.tenant_id
            or tenant_id not in {actor.tenant_id, ASSET_OWNER_TENANT_ID} and not has_any_role(roles, {'SU'})):
            raise ScopeDenied()
        with self.ports(actor, tenant_id, context=context) as records:
            _scope(records, actor, tenant_id)
            ordering = (Sort('update_time', descending=True), Sort('knowledge_id', descending=True),
                        Sort('index_name', descending=True)) if ordered else (Sort('knowledge_id'),)
            result, default, loaded = [], None, False
            for row in _pages(records, CATALOG, RecordQuery(order_by=ordering), context):
                if row['knowledge_sources'] == 'datamate':
                    continue
                permission = metadata_permission(row, actor, roles, groups, view)
                if permission is None:
                    continue
                row = dict(row)
                row['_metadata_revision'] = knowledge_search_revision(row)
                row['permission'] = permission
                if row['group_ids']:
                    row['group_ids'] = convert_string_to_list(row['group_ids'])
                else:
                    if not loaded:
                        default, loaded = _default_group(records, context), True
                    row['group_ids'] = [default] if default else []
                for field in ('create_time', 'update_time', 'last_summary_time'):
                    value = row.get(field)
                    if isinstance(value, str) and value.endswith('+00:00'):
                        row[field] = value[:-6] + 'Z'
                result.append(row)
            return result

    def tags(self, actor, tenant_id, rows, *, context):
        values = {}
        if rows:
            with self.ports(actor, tenant_id, context=context) as records:
                _scope(records, actor, tenant_id)
                for start in range(0, len(rows), 500):
                    ids = [row['index_name'] for row in rows[start:start+500]]
                    query = RecordQuery(where=Junction('and', (Comparison('resource_type', 'eq', 'knowledge_base'),
                        Comparison('resource_id', 'in', ids))), order_by=(Sort('resource_id'), Sort('assignment_id')))
                    for item in _pages(records, TAGS, query, context):
                        if item['display_value']:
                            values.setdefault(item['resource_id'], []).append(item['display_value'])
        return [{**row, 'tags': list(dict.fromkeys(values.get(row['index_name'], [])))} for row in rows]

    def backfill(self, actor, row, model_name, *, context):
        with self.ports(actor, row['tenant_id'], context=context) as records:
            _scope(records, actor, row['tenant_id'])
            current = records.get(CATALOG, row['knowledge_id'], context=context)
            if current is None or current['embedding_model_name'] is not None:
                return
            receipt = records.patch(CATALOG, row['knowledge_id'], FieldPatch(set_values={'embedding_model_name': model_name}),
                                    expected=Revision(str(row['version'])), context=context)
            if receipt.outcome is not WriteOutcome.CONFIRMED:
                raise Conflict()
