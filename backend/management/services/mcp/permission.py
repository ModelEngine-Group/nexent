# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Apply the existing MCP list's public, owner and group edit rules to writes."""

from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES


def can_edit_mcp_record(record: dict, user_id: str, role: str, group_ids: list) -> bool:
    owner = record.get("created_by") or record.get("user_id")
    if str(owner or "") == str(user_id) or record.get("group_ids") is None:
        return True
    allowed = {value.strip() for value in str(record.get("group_ids") or "").split(",") if value.strip()}
    permission = str(record.get("ingroup_permission") or "READ_ONLY").upper()
    if permission == "PRIVATE" or not allowed.intersection(map(str, group_ids)):
        return False
    return str(role).upper() in CAN_EDIT_ALL_USER_ROLES or permission == "EDIT"
