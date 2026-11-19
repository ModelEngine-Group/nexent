# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read PRIVATE subject accounting without replacing the authenticated actor."""

import logging
from functools import partial

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.services.knowledge_base.personal_capacity_access import (
    PersonalCapacityAccess,
)
from management.services.knowledge_base.quota_authorization import (
    quota_identity_roles,
    require_quota_scope,
)
from management.services.knowledge_base.quota_rules import parse_personal_quota
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
)
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery

from infrastructure.personal_capacity import personal_capacity_ports
from infrastructure.rdb.storage_ledger import LEDGER
from infrastructure.tenant_quota_read import CATALOG, CONFIGS

logger = logging.getLogger(__name__)
_usage_ports = partial(personal_capacity_ports, usage=True)


class PersonalCapacityReader(PersonalCapacityAccess):
    def __init__(self, *, ports=_usage_ports):
        self.ports = ports

    def read(self, tenant, actor, subject, *, strict=True, context):
        return self._read(tenant, actor, subject, strict=strict, own=False, context=context)

    def authorize_management(self, tenant, actor, *, context):
        context.remaining()
        with self.ports(actor, context=context, writable=False) as (identity, permissions, _):
            self._authorize(identity, permissions, actor, tenant, False, context)

    def read_management(self, tenant, actor, *, subject=None, context):
        return self._read(tenant, actor, subject, strict=False, own=False, management=True, context=context)

    def authorize_self(self, actor, *, context):
        context.remaining()
        with self.ports(actor, context=context, writable=False) as (identity, _, _):
            quota_identity_roles(identity, actor, context=context)

    def read_self(self, actor, *, context):
        return self._read(actor.tenant_id, actor, actor.user_id, strict=True, own=True, context=context)

    def _read(self, tenant, actor, subject, *, strict, own, management=False, context):
        context.remaining()
        with self.ports(actor, context=context, writable=False) as (identity, permissions, open_records):
            def authorize():
                if own:
                    quota_identity_roles(identity, actor, context=context)
                else:
                    self._authorize(identity, permissions, actor, tenant, not management, context)

            authorize()
            records = open_records(tenant)
            require_quota_scope(records, actor, tenant)
            rows, cursor, seen = [], None, set()
            terms = [Comparison('ingroup_permission', 'eq', 'PRIVATE'), Comparison('delete_flag', 'ne', 'Y')]
            if subject is not None:
                terms.append(Comparison('created_by', 'eq', subject))
            query = RecordQuery(where=Junction('and', tuple(terms)))
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
            result = {'knowledge_bases': rows, 'source_bytes_by_kb': by_knowledge, 'personal_bytes': total}
            if own:
                value, source = None, 'unlimited'
                for key, kind in [('PERSONAL_KB_QUOTA_' + subject, 'individual'), ('PERSONAL_KB_QUOTA_DEFAULT', 'default')]:
                    page = records.query(CONFIGS, RecordQuery(where=Comparison('config_key', 'eq', key)),
                                         PageRequest(limit=1), context=context)
                    value = parse_personal_quota(page.items[0]['config_value']) if page.items else None
                    if value is not None:
                        source = kind
                        break
                result.update(quota_bytes=value, quota_source=source)
            if management:
                subjects = sorted({row['created_by'] for row in rows if row['created_by']})
                quotas, default = self._configuration(records, subjects, context)
                result.update(quotas=quotas, default_quota=default)
            authorize()
            context.remaining()
            return result

    def _configuration(self, records, subjects, context):
        keys = ['PERSONAL_KB_QUOTA_' + subject for subject in subjects] + ['PERSONAL_KB_QUOTA_DEFAULT']
        configs = {}
        for start in range(0, len(keys), 500):
            cursor, seen = None, set()
            query = RecordQuery(where=Comparison('config_key', 'in', keys[start:start + 500]))
            while True:
                page = records.query(CONFIGS, query, PageRequest(limit=500, cursor=cursor), context=context)
                configs.update((row['config_key'], row['config_value']) for row in page.items)
                if page.next_cursor is None:
                    break
                if page.next_cursor in seen:
                    raise Conflict()
                seen.add(page.next_cursor)
                cursor = page.next_cursor
        default = parse_personal_quota(configs.get('PERSONAL_KB_QUOTA_DEFAULT'))
        result = {}
        for subject in subjects:
            value = parse_personal_quota(configs.get('PERSONAL_KB_QUOTA_' + subject))
            result[subject] = (value, 'individual') if value is not None else (
                (default, 'default') if default is not None else (None, 'unlimited'))
        return result, default
