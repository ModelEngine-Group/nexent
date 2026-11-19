# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prepare allocation inputs independently of model or vector-store availability."""

from contracts.constants.constants import ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID
from contracts.knowledge import (
    KEY_PLATFORM_CAPACITY_BYTES,
    KEY_TENANT_HARD_LIMIT_BYTES,
    STORAGE_LEDGER_DATASET,
)
from contracts.roles import has_any_role
from management.services.knowledge_base.quota_authorization import (
    quota_identity_roles,
    require_quota_scope,
)
from management.services.knowledge_base.quota_read import read_quota_config
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import Comparison, PageRequest, RecordQuery

from infrastructure.platform_quota_read import DISCOVERY, platform_quota_read_ports


class QuotaAllocationReader:
    def __init__(self, *, ports=platform_quota_read_ports):
        self.ports = ports

    def _authorize(self, identity, actor, tenant, context):
        roles = quota_identity_roles(identity, actor, context=context)
        if (not has_any_role(roles, {'SU', 'ASSET_OWNER'})
                and (tenant != actor.tenant_id or not has_any_role(roles, {'ADMIN'}))):
            raise ScopeDenied()

    def read(self, tenant, actor, *, context):
        context.remaining()
        with self.ports(actor, context=context, usage_tenant=tenant) as (identity, discover, open_records):
            self._authorize(identity, actor, tenant, context)

            def records(resource_tenant):
                port = open_records(resource_tenant)
                require_quota_scope(port, actor, resource_tenant)
                return port

            def config(port, key):
                return read_quota_config(port, key, context=context)

            def numeric(raw):
                try:
                    return int(raw) if raw is not None else None
                except (ValueError, TypeError):
                    return None

            target = records(tenant)
            usage = target.sum(STORAGE_LEDGER_DATASET, 'raw_bytes',
                               RecordQuery(where=Comparison('status', 'eq', 'COMMITTED')), context=context)
            current = numeric(config(target, KEY_TENANT_HARD_LIMIT_BYTES))
            editable = config(target, 'KB_QUOTA_HARD_LIMIT_EDITABLE')
            capacity = numeric(config(records(ASSET_OWNER_TENANT_ID), KEY_PLATFORM_CAPACITY_BYTES))
            discovery = discover()
            require_quota_scope(discovery, actor, actor.tenant_id)
            allocated, cursor, seen = 0, None, set()
            while True:
                page = discovery.query(DISCOVERY, RecordQuery(), PageRequest(limit=500, cursor=cursor), context=context)
                for row in page.items:
                    resource_tenant = row['tenant_id']
                    if resource_tenant.strip() in ('', DEFAULT_TENANT_ID, ASSET_OWNER_TENANT_ID):
                        continue
                    limit = (current if resource_tenant == tenant else
                             numeric(config(records(resource_tenant), KEY_TENANT_HARD_LIMIT_BYTES)))
                    if limit is not None:
                        allocated += limit
                if page.next_cursor is None:
                    break
                if page.next_cursor in seen:
                    raise Conflict()
                seen.add(page.next_cursor)
                cursor = page.next_cursor
            self._authorize(identity, actor, tenant, context)
            context.remaining()
            return {'usage_bytes': usage, 'capacity_bytes': capacity, 'current_limit_bytes': current,
                    'total_allocated_bytes': allocated, 'hard_limit_editable': editable != 'false' if editable else True}
