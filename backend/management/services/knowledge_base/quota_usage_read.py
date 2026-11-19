# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Collect quota inputs without omitting retained or inaccessible source objects."""

from functools import partial

from contracts.knowledge import STORAGE_LEDGER_DATASET as LEDGER
from management.services.knowledge_base.quota_read import TenantQuotaReader
from nexent.storage.errors import Conflict
from nexent.storage.models import Comparison, PageRequest, RecordQuery

from infrastructure.tenant_quota_read import CATALOG, tenant_quota_read_ports

_usage_ports = partial(tenant_quota_read_ports, usage=True)


class TenantQuotaUsageReader(TenantQuotaReader):
    def __init__(self, *, ports=_usage_ports):
        super().__init__(ports=ports)

    def _read_records(self, records, context):
        result = super()._read_records(records, context)
        rows, cursor, seen = [], None, set()
        query = RecordQuery(where=Comparison('delete_flag', 'ne', 'Y'))
        while True:
            page = records.query(CATALOG, query, PageRequest(limit=500, cursor=cursor), context=context)
            rows.extend(page.items)
            if page.next_cursor is None:
                break
            if page.next_cursor in seen:
                raise Conflict()
            seen.add(page.next_cursor)
            cursor = page.next_cursor
        committed = RecordQuery(where=Comparison('status', 'eq', 'COMMITTED'))
        by_kb = records.sum_by(LEDGER, 'raw_bytes', 'knowledge_id', committed, context=context)
        total = records.sum(LEDGER, 'raw_bytes', committed, context=context)
        return {
            **result,
            'knowledge_bases': rows,
            'source_bytes_by_kb': by_kb,
            'tenant_source_bytes': total,
        }
