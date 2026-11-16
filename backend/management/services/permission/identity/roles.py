# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Role options and application audit around atomic membership writes."""

import logging

from contracts.errors.exceptions import NotFoundException
from contracts.roles import ORDINARY_ROLES, roles_from_record
from management.db.client import get_db_session
from management.db.identity.membership import (
    api_only_account,
    get_user_tenant_by_user_id,
)
from management.db.identity.roles import replace_member_roles
from permissions.role_assignment import check_managed_target

logger = logging.getLogger(__name__)


def assignable_roles(actor_id, user_id):
    actor, target = get_user_tenant_by_user_id(actor_id), get_user_tenant_by_user_id(user_id)
    if not actor or not target:
        raise NotFoundException("User not found")
    check_managed_target(actor, target)
    locked = ["ADMIN"] if actor_id == user_id and "ADMIN" in roles_from_record(target) else []
    with get_db_session() as session:
        grantable = frozenset({"DEV", "USER"}) if api_only_account(session, user_id) else ORDINARY_ROLES
    return {
        "grantable_roles": sorted(grantable),
        "revocable_roles": sorted(grantable - set(locked)),
        "locked_roles": locked,
        "reasons": {"ADMIN": "Cannot remove your own ADMIN role"} if locked else {},
    }


def replace_roles(actor_id, user_id, values, *, legacy=False):
    target, old, requested = replace_member_roles(actor_id, user_id, values, legacy=legacy)
    if old != requested:
        logger.info(
            "Role assignment actor=%s target=%s tenant=%s before=%s after=%s",
            actor_id,
            user_id,
            target["tenant_id"],
            old,
            requested,
        )
    return get_user_tenant_by_user_id(user_id)
