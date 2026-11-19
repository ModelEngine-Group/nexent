# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validation and resolution of explicit resource group grants."""

from collections.abc import Iterable

from pydantic import TypeAdapter

from contracts.constants.constants import PERMISSION_EDIT, PERMISSION_PRIVATE, PERMISSION_READ
from contracts.group_permissions import GroupPermission

_GROUP_RULES = TypeAdapter(list[GroupPermission])


def validate_group_permissions(value, tenant_id: str) -> list[dict]:
    from management.db.identity.group import filter_tenant_group_ids

    rules = _GROUP_RULES.validate_python(value)
    ids = [rule.group_id for rule in rules]
    if len(ids) != len(set(ids)):
        raise ValueError("Each group may appear only once")
    if ids and set(filter_tenant_group_ids(ids, tenant_id)) != set(ids):
        raise ValueError("Every group must be active and belong to the resource tenant")
    return [rule.model_dump() for rule in rules]


def matching_group_permission(rules: list[dict], user_groups: Iterable[object]) -> str | None:
    user_ids = {str(group_id) for group_id in user_groups}
    result = None
    for rule in rules:
        if str(rule.get("group_id")) not in user_ids:
            continue
        if rule.get("permission") == PERMISSION_EDIT:
            return PERMISSION_EDIT
        if rule.get("permission") == PERMISSION_READ:
            result = PERMISSION_READ
    return result


def legacy_group_permission(rules: list[dict]) -> str:
    """Expose explicit sharing conservatively to clients that know one level."""
    return PERMISSION_READ if rules else PERMISSION_PRIVATE
