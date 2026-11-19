# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest

from management.db.identity import group
from permissions.dac import ResourceAccessControl
from permissions.group_sharing import matching_group_permission, validate_group_permissions
from permissions.models import Resource

RULES = [{"group_id": 1, "permission": "READ_ONLY"}, {"group_id": 2, "permission": "EDIT"}]


@pytest.mark.parametrize(("groups", "permission"), [
    ([1], "READ_ONLY"), ([2], "EDIT"), ([1, 2], "EDIT"), ([], None), ([3], None),
])
def test_explicit_group_resolution(groups, permission):
    assert matching_group_permission(RULES, groups) == permission
    resource = Resource("knowledge_base", "kb", "tenant", "owner", "READ_ONLY", [1, 2], group_permissions=RULES)
    assert ResourceAccessControl.check(resource, "member", "DEV", groups, "tenant").permission_label == permission
    assert not ResourceAccessControl.check(resource, "member", "DEV", groups, "other").can_read


def test_cleared_rules_never_fall_back_to_legacy_membership():
    resource = Resource("knowledge_base", "kb", "tenant", "owner", "EDIT", [2], group_permissions=[])
    assert not ResourceAccessControl.check(resource, "member", "DEV", [2], "tenant").can_read
    assert ResourceAccessControl.check(resource, "owner", "DEV", [], "tenant").can_edit


def test_rule_validation_rejects_duplicate_and_foreign_groups(monkeypatch):
    monkeypatch.setattr(group, "filter_tenant_group_ids", lambda ids, tenant: [i for i in ids if i in {1, 2}])
    assert validate_group_permissions(RULES, "tenant") == RULES
    with pytest.raises(ValueError, match="only once"):
        validate_group_permissions([*RULES, {"group_id": 1, "permission": "EDIT"}], "tenant")
    with pytest.raises(ValueError, match="belong"):
        validate_group_permissions([{"group_id": 3, "permission": "EDIT"}], "tenant")
    with pytest.raises(ValueError):
        validate_group_permissions([{"group_id": True, "permission": "EDIT"}], "tenant")
