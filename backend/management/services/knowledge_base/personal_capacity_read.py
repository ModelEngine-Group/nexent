# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read PRIVATE subject accounting without replacing the authenticated actor."""

import logging
from functools import partial

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.services.knowledge_base.personal_capacity_access import (
    PersonalCapacityAccess,
)
from management.services.knowledge_base.quota_authorization import require_quota_scope
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
)
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery

from infrastructure.personal_capacity import personal_capacity_ports
from infrastructure.rdb.storage_ledger import LEDGER
from infrastructure.tenant_quota_read import CATALOG

logger = logging.getLogger(__name__)
_usage_ports = partial(personal_capacity_ports, usage=True)


class PersonalCapacityReader(PersonalCapacityAccess):
    def __init__(self, *, ports=_usage_ports):
        self.ports = ports

    def read(self, tenant, actor, subject, *, strict=True, context):
        context.remaining()
        with self.ports(actor, context=context, writable=False) as (identity, permissions, open_records):
            self._authorize(identity, permissions, actor, tenant, True, context)
            records = open_records(tenant)
            require_quota_scope(records, actor, tenant)
            rows, cursor, seen = [], None, set()
            query = RecordQuery(where=Junction('and', (
                Comparison('created_by', 'eq', subject), Comparison('ingroup_permission', 'eq', 'PRIVATE'),
                Comparison('delete_flag', 'ne', 'Y'),
            )))
            while True:
                page = records.query(CATALOG, query, PageRequest(limit=500, cursor=cursor), context=context)
                rows.extend(page.items)
                if page.next_cursor is None:
                    break
                if page.next_cursor in seen:
                    raise Conflict()
                seen.add(page.next_cursor)
                cursor = page.next_cursor
            by_knowledge = {}
            ids = [row['knowledge_id'] for row in rows]
            try:
                for offset in range(0, len(ids), 500):
                    by_knowledge.update(records.sum_by(LEDGER, 'raw_bytes', 'knowledge_id',
                        RecordQuery(where=Junction('and', (Comparison('status', 'eq', 'COMMITTED'),
                            Comparison('knowledge_id', 'in', ids[offset:offset + 500])))), context=context))
            except (DeadlineExceeded, OperationCancelled, ScopeDenied, Conflict):
                raise
            except Exception as error:
                if strict:
                    raise AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE,
                        f'Failed to query source storage stats: {error}') from error
                logger.warning('personal_capacity_source_unavailable operation_id=%s exception_type=%s',
                               context.operation_id, type(error).__name__)
                by_knowledge = {}
            # Keep legacy index-keyed projection when historical KB aliases collide.
            by_index = {row['index_name']: by_knowledge.get(row['knowledge_id'], 0) for row in rows if row['index_name']}
            total = sum(by_index[row['index_name']] for row in rows if row['index_name'])
            self._authorize(identity, permissions, actor, tenant, True, context)
            context.remaining()
            return {'knowledge_bases': rows, 'source_bytes_by_kb': by_knowledge, 'personal_bytes': total}
