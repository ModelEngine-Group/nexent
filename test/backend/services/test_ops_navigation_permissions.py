# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Return navigation identifiers without interpreting frontend routes."""

import pytest

from management.services.permission.identity.authentication import format_role_permissions


def nav(subtype):
    return {
        "permission_category": "VISIBILITY",
        "permission_type": "LEFT_NAV_MENU",
        "permission_subtype": subtype,
    }


@pytest.mark.parametrize(
    "identifier,route",
    [
        ("ops-dashboard", "ops-dashboard"),
        ("ops-configuration", "ops-configuration"),
        ("/ops/dashboard", "/ops/dashboard"),
        ("/ops/configuration", "/ops/configuration"),
        ("/resource-manage", "/resource-manage"),
        ("agents", "agents"),
    ],
)
def test_navigation_identifiers_are_returned_unchanged(identifier, route):
    assert format_role_permissions([nav(identifier)]) == {
        "permissions": [],
        "accessiblePages": [route],
    }


def test_mixed_legacy_and_new_identifiers_preserve_order_without_duplicates():
    grants = [
        nav("/agents"),
        nav("ops-configuration"),
        nav("/ops/dashboard"),
        nav("ops-dashboard"),
        nav("/ops/configuration"),
        nav("ops-configuration"),
    ]
    snapshot = [dict(grant) for grant in grants]
    assert format_role_permissions(grants) == {
        "permissions": [],
        "accessiblePages": [
            "/agents", "ops-configuration", "/ops/dashboard",
            "ops-dashboard", "/ops/configuration",
        ],
    }
    assert grants == snapshot


def test_page_identifiers_do_not_change_resource_action_grants():
    assert format_role_permissions([
        nav("ops-dashboard"),
        {
            "permission_category": "RESOURCE",
            "permission_type": "OPS.DASHBOARD",
            "permission_subtype": "READ",
        },
        {
            "permission_category": "RESOURCE",
            "permission_type": "MODEL",
            "permission_subtype": "ops-configuration",
        },
    ]) == {
        "permissions": ["ops.dashboard:read", "model:ops-configuration"],
        "accessiblePages": ["ops-dashboard"],
    }


@pytest.mark.parametrize("grants", [[], [{}], [nav("")], [nav(None)], [
    {"permission_type": "OTHER", "permission_subtype": "ops-dashboard"},
]])
def test_missing_or_unrelated_grants_do_not_add_navigation_access(grants):
    assert format_role_permissions(grants) == {"permissions": [], "accessiblePages": []}
