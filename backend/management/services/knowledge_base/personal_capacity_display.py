# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Load display-only values for creators selected by authorized PRIVATE KB input."""

import logging

from management.services.knowledge_base.quota_authorization import require_quota_scope
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
)
from nexent.storage.models import Comparison, PageRequest, RecordQuery

from infrastructure.personal_capacity_display import (
    CAS,
    EMAILS,
    personal_capacity_display_ports,
)

logger = logging.getLogger(__name__)


class PersonalCapacityDisplay:
    def __init__(self, *, ports=personal_capacity_display_ports):
        self.ports = ports

    def _rows(self, records, dataset, subjects, context):
        result = []
        for start in range(0, len(subjects), 500):
            cursor, seen = None, set()
            query = RecordQuery(where=Comparison('user_id', 'in', subjects[start:start + 500]))
            while True:
                page = records.query(dataset, query, PageRequest(limit=500, cursor=cursor), context=context)
                result.extend(page.items)
                if page.next_cursor is None:
                    break
                if page.next_cursor in seen:
                    raise Conflict()
                seen.add(page.next_cursor)
                cursor = page.next_cursor
        return result

    def read(self, tenant, actor, subjects, *, context):
        context.remaining()
        subjects = sorted({value for value in subjects if isinstance(value, str) and value})
        if not subjects:
            return {}, {}
        with self.ports(actor, tenant, context=context) as records:
            require_quota_scope(records, actor, tenant)
            emails = {row['user_id']: row['user_email'] for row in self._rows(records, EMAILS, subjects, context)
                      if row['user_email']}
            identities = {}
            try:
                for row in self._rows(records, CAS, subjects, context):
                    name = (row['provider_username'] or '').strip()
                    if name and row['user_id'] not in identities:
                        identities[row['user_id']] = {'cas_username': name}
            except (Conflict, DeadlineExceeded, OperationCancelled, ScopeDenied):
                raise
            except Exception as error:  # noqa: BLE001 - Preserve the existing optional CAS display failure branch.
                identities = {}
                logger.warning('personal_capacity_cas_display_unavailable operation_id=%s exception_type=%s',
                               context.operation_id, type(error).__name__)
            context.remaining()
            return emails, identities
