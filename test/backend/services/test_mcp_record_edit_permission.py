# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Local MCP writes preserve the existing owner, public and group edit rules."""

import pytest

from management.services.mcp.permission import can_edit_mcp_record


@pytest.mark.parametrize("owner,groups,permission,role,memberships,expected", [
    ("actor", "1", "PRIVATE", "DEV", [], True),
    ("other", None, "READ_ONLY", "USER", [], True),
    ("other", "1", "EDIT", "DEV", [1], True),
    ("other", "1", "READ_ONLY", "DEV", [1], False),
    ("other", "1", "READ_ONLY", "ADMIN", [1], True),
    ("other", "1", "PRIVATE", "ADMIN", [1], False),
    ("other", "1", "EDIT", "ADMIN", [2], False),
    ("other", "1", "EDIT", "DEV", [2], False),
    ("other", "", "EDIT", "DEV", [1], False),
    ("other", " 1, 2 ", "EDIT", "DEV", [2], True),
])
def test_record_edit_permission(owner, groups, permission, role, memberships, expected):
    record = {"created_by": owner, "group_ids": groups, "ingroup_permission": permission}
    assert can_edit_mcp_record(record, "actor", role, memberships) is expected
