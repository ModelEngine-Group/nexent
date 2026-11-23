# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Apply the catalog's edit rules to a tenant-owned MCP service."""

from contracts.constants.constants import PERMISSION_EDIT, PERMISSION_READ


def catalog_permission(record, user_id, can_edit_all, group_ids):
    if record.get("group_ids") is None:
        return PERMISSION_EDIT
    owner = record.get("created_by") or record.get("user_id")
    if user_id is not None and (can_edit_all or str(owner) == str(user_id)):
        return PERMISSION_EDIT
    allowed = {g.strip() for g in record["group_ids"].split(",") if g.strip()}
    if (
        allowed.intersection(str(g) for g in group_ids or ())
        and (record.get("ingroup_permission") or "READ_ONLY").upper() == "EDIT"
    ):
        return PERMISSION_EDIT
    return PERMISSION_READ
