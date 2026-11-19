# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Live quota identity checks do not depend on KB visibility or user groups."""

from contracts.roles import roles_from_record
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Comparison, PageRequest, RecordQuery


def require_quota_scope(port, actor, tenant):
    scope = port.scope
    if (
        scope.service_role != "management"
        or scope.system
        or scope.resource_prefix
        or scope.tenant_id != tenant
        or scope.actor_id != actor.user_id
    ):
        raise ScopeDenied()


def quota_identity_roles(identity, actor, *, context):
    require_quota_scope(identity, actor, actor.tenant_id)
    rows = []
    for dataset in ("cleanse_memberships", "cleanse_accounts"):
        page = identity.query(
            dataset,
            RecordQuery(where=Comparison("user_id", "eq", actor.user_id)),
            PageRequest(limit=2),
            context=context,
        )
        if len(page.items) != 1 or page.next_cursor:
            raise ScopeDenied()
        rows.append(page.items[0])
    member, account = rows
    if member.get("tenant_id") != actor.tenant_id:
        raise ScopeDenied()
    try:
        return roles_from_record(account)
    except ValueError as error:
        raise ScopeDenied() from error
