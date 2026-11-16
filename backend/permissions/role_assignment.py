# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Pure authorization policy shared by locked membership write paths."""

from contracts.errors.exceptions import ForbiddenError
from contracts.roles import has_any_role, roles_from_record


def check_managed_target(actor, target):
    actor_roles = roles_from_record(actor)
    if has_any_role(roles_from_record(target), {"SU", "ASSET_OWNER"}):
        raise ForbiddenError("Special identities are not editable through ordinary role management")
    if has_any_role(actor_roles, {"SU"}):
        return
    if not has_any_role(actor_roles, {"ADMIN"}) or actor["tenant_id"] != target["tenant_id"]:
        raise ForbiddenError("Not authorized to manage this user")
