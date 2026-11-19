# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Share existing first-record and audited mutation rules across quota policies."""

from nexent.storage.errors import Conflict
from nexent.storage.models import Comparison, FieldPatch, PageRequest, RecordQuery

from infrastructure.quota_write import CONFIGS


class QuotaConfigurationRecords:
    def _row(self, records, key, context):
        page = records.query(CONFIGS, RecordQuery(where=Comparison('config_key', 'eq', key)),
                             PageRequest(limit=1), context=context)
        return page.items[0] if page.items else None

    def _value(self, records, key, context):
        row = self._row(records, key, context)
        return row['config_value'] if row else None

    def _set(self, records, key, value, actor, context):
        row = self._row(records, key, context)
        if row is None:
            records.create(CONFIGS, {'config_key': key, 'config_value': str(value),
                'user_id': actor.user_id, 'value_type': 'single'}, context=context)
            return
        receipt = records.patch(CONFIGS, row['tenant_config_id'],
            FieldPatch(set_values={'config_value': str(value)}), context=context)
        if not receipt.matched:
            raise Conflict(operation_id=context.operation_id)

    def _delete(self, records, key, context):
        row = self._row(records, key, context)
        if row and not records.delete(CONFIGS, row['tenant_config_id'], context=context).deleted:
            raise Conflict(operation_id=context.operation_id)
