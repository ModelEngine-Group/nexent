# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize the actual editor and apply existing source-byte quotas through SI."""

import logging

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.knowledge import KEY_TENANT_HARD_LIMIT_BYTES, STORAGE_LEDGER_DATASET
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from management.services.knowledge_base.quota_rules import (
    check_kb_capacity,
    check_tenant_capacity,
    check_user_capacity,
    parse_personal_quota,
    source_sizes,
)
from management.services.knowledge_base.source_reference import (
    resolve_storage_reference,
)
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
)
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery, Sort

from infrastructure.knowledge_catalog import CATALOG
from infrastructure.knowledge_document_quota import CONFIGS, document_quota_ports

logger = logging.getLogger(__name__)


def _config(records, key, context):
    page = records.query(CONFIGS, RecordQuery(where=Comparison('config_key', 'eq', key)), PageRequest(limit=2), context=context)
    if page.next_cursor or len(page.items) > 1:
        raise Conflict()
    return page.items[0]['config_value'] if page.items else None


def _usage(catalog, ledger, actor, context):
    by_index, by_user, seen, cursor = {}, {}, set(), None
    total = 0
    while True:
        page = catalog.query(CATALOG, RecordQuery(fields=('knowledge_id', 'index_name', 'created_by'),
            where=Comparison('ingroup_permission', 'eq', 'PRIVATE'), order_by=(Sort('knowledge_id'),)),
            PageRequest(limit=500, cursor=cursor), context=context)
        selected = [row for row in page.items if row['index_name']]
        if selected:
            amounts = ledger.sum_by(STORAGE_LEDGER_DATASET, 'raw_bytes', 'knowledge_id', RecordQuery(where=Junction('and', (
                Comparison('status', 'eq', 'COMMITTED'), Comparison('knowledge_id', 'in', [row['knowledge_id'] for row in selected]),
            ))), context=context)
            for row in selected:
                index = row['index_name']
                if index in by_index:
                    raise Conflict()
                amount = amounts.get(row['knowledge_id'], 0)
                by_index[index] = amount
                total += amount
                if row['created_by'] == actor.user_id:
                    by_user[actor.user_id] = by_user.get(actor.user_id, 0) + amount
        if page.next_cursor is None:
            return total, by_user.get(actor.user_id, 0), by_index
        if page.next_cursor in seen:
            raise Conflict()
        seen.add(page.next_cursor)
        cursor = page.next_cursor


def _pending(ledger, row, data, context):
    sizes = source_sizes(data)
    references = {key: ref for key in sizes if (ref := resolve_storage_reference(key)) is not None}
    buckets = {}
    for ref in references.values():
        buckets.setdefault(ref.bucket_name, set()).add(ref.object_name)
    committed = {}
    for bucket, keys in buckets.items():
        names = sorted(keys)
        for offset in range(0, len(names), 500):
            page = ledger.query(STORAGE_LEDGER_DATASET, RecordQuery(where=Junction('and', (
                Comparison('knowledge_id', 'eq', row['knowledge_id']), Comparison('status', 'eq', 'COMMITTED'),
                Comparison('bucket_name', 'eq', bucket), Comparison('object_name', 'in', names[offset:offset + 500]),
            ))), PageRequest(limit=500), context=context)
            if page.next_cursor:
                raise Conflict()
            for item in page.items:
                identity = bucket, item['object_name']
                if identity in committed:
                    raise Conflict()
                committed[identity] = item['raw_bytes']
    # Preserve the existing zero-valued key projection, including unresolved ledger rows.
    by_path = {path: committed.get((ref.bucket_name, ref.object_name), 0) for path, ref in references.items()}
    return sum(size for path, size in sizes.items() if path not in by_path)


def prepare_document_admission(index_name, data, actor, *, context, reader=None, ports=document_quota_ports):
    context.remaining()
    row = (reader or KnowledgeFileReader()).knowledge(index_name, actor, edit=True, context=context)
    if row['ingroup_permission'] != 'PRIVATE':
        return
    try:
        with ports(actor, context=context) as stores:
            if len(stores) != 3 or any(store.scope.service_role != 'management' or store.scope.system
                or store.scope.resource_prefix or store.scope.actor_id != actor.user_id or store.scope.tenant_id != actor.tenant_id
                for store in stores):
                raise ScopeDenied()
            catalog, ledger, configs = stores
            pending = _pending(ledger, row, data, context)
            tenant_bytes, user_bytes, by_index = _usage(catalog, ledger, actor, context)
            raw = _config(configs, KEY_TENANT_HARD_LIMIT_BYTES, context)
            try:
                hard_limit = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                hard_limit = None
            check_tenant_capacity(tenant_bytes, pending, hard_limit)
            individual = parse_personal_quota(_config(configs, 'PERSONAL_KB_QUOTA_' + actor.user_id, context))
            limit, source = individual, 'individual'
            if limit is None:
                limit, source = parse_personal_quota(_config(configs, 'PERSONAL_KB_QUOTA_DEFAULT', context)), 'default'
            check_user_capacity(user_bytes, pending, limit, source, actor.user_id)
            check_kb_capacity(by_index.get(row['index_name'], 0), pending,
                              parse_personal_quota(row.get('quota_limit_bytes')), row['index_name'])
            context.remaining()
    except (AppException, DeadlineExceeded, OperationCancelled):
        raise
    except Exception as error:
        logger.warning('knowledge_document_quota_unavailable operation_id=%s exception_type=%s',
                       context.operation_id, type(error).__name__)
        raise AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE,
                           f'Personal KB quota service unavailable: {error}') from error
