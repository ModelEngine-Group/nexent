# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read platform quota display inputs after current privileged authorization."""

from contracts.constants.constants import (
    ASSET_OWNER_TENANT_ID,
    DEFAULT_TENANT_ID,
    TENANT_NAME,
)
from contracts.knowledge import KEY_PLATFORM_CAPACITY_BYTES, KEY_TENANT_HARD_LIMIT_BYTES
from contracts.roles import has_any_role
from management.services.knowledge_base.quota_authorization import (
    quota_identity_roles,
    require_quota_scope,
)
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import Comparison, PageRequest, RecordQuery, Sort

from infrastructure.platform_quota_read import DISCOVERY, platform_quota_read_ports
from infrastructure.tenant_quota_read import CONFIGS


class PlatformQuotaReader:
    def __init__(self, *, ports=platform_quota_read_ports):
        self.ports = ports

    def _authorize(self, identity, actor, context):
        roles = quota_identity_roles(identity, actor, context=context)
        if not has_any_role(roles, {'SU', 'ASSET_OWNER'}):
            raise ScopeDenied()
        return roles

    def authorize(self, actor, *, context):
        context.remaining()
        with self.ports(actor, context=context) as (identity, _, __):
            roles = self._authorize(identity, actor, context)
            context.remaining()
            return roles

    def read(self, actor, *, context):
        context.remaining()
        with self.ports(actor, context=context) as (identity, discover, open_records):
            self._authorize(identity, actor, context)
            discovery = discover()
            require_quota_scope(discovery, actor, actor.tenant_id)

            def config(records, key):
                page = records.query(CONFIGS, RecordQuery(where=Comparison('config_key', 'eq', key)),
                                     PageRequest(limit=1), context=context)
                return page.items[0]['config_value'] if page.items else None

            def records(tenant):
                port = open_records(tenant)
                require_quota_scope(port, actor, tenant)
                return port

            def numeric(raw):
                try:
                    return int(raw) if raw is not None else None
                except (TypeError, ValueError):
                    return None

            capacity = numeric(config(records(ASSET_OWNER_TENANT_ID), KEY_PLATFORM_CAPACITY_BYTES))
            tenants, cursor, seen = [], None, set()
            while True:
                page = discovery.query(DISCOVERY, RecordQuery(order_by=(Sort('latest_created_at', True), Sort('tenant_id'))),
                                       PageRequest(limit=500, cursor=cursor), context=context)
                for row in page.items:
                    tenant = row['tenant_id']
                    if tenant.strip() in ('', DEFAULT_TENANT_ID, ASSET_OWNER_TENANT_ID):
                        continue
                    port = records(tenant)
                    tenants.append({'tenant_id': tenant, 'tenant_name': config(port, TENANT_NAME) or tenant,
                                    'hard_limit_bytes': numeric(config(port, KEY_TENANT_HARD_LIMIT_BYTES))})
                if page.next_cursor is None:
                    break
                if page.next_cursor in seen:
                    raise Conflict()
                seen.add(page.next_cursor)
                cursor = page.next_cursor
            self._authorize(identity, actor, context)
            context.remaining()
            return {'capacity_bytes': capacity, 'tenants': tenants}
