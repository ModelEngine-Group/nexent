# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Collect personal upload limits without querying a database outside SI."""

from management.services.knowledge_base.quota_read import read_quota_config
from management.services.knowledge_base.quota_rules import parse_personal_quota
from management.services.knowledge_base.quota_usage_read import TenantQuotaUsageReader


class UploadQuotaReader(TenantQuotaUsageReader):
    def _read_records(self, records, context):
        result = super()._read_records(records, context)
        user = records.scope.actor_id
        limit = parse_personal_quota(read_quota_config(records, 'PERSONAL_KB_QUOTA_' + user, context=context))
        source = 'individual'
        if limit is None:
            limit = parse_personal_quota(read_quota_config(records, 'PERSONAL_KB_QUOTA_DEFAULT', context=context))
            source = 'default' if limit is not None else 'unlimited'
        private = [row for row in result['knowledge_bases'] if row['created_by'] == user
                   and row['ingroup_permission'] == 'PRIVATE' and row['index_name']]
        # Preserve the original per-index accounting when legacy names collide.
        by_index = {row['index_name']: result['source_bytes_by_kb'].get(row['knowledge_id'], 0) for row in private}
        return {**result, 'personal_bytes': sum(by_index[row['index_name']] for row in private),
                'personal_limit': limit, 'personal_source': source}
