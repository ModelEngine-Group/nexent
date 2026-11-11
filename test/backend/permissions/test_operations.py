# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Operations grants and scope are independent of business permissions."""

import pytest
from fastapi import HTTPException, Request

from contracts.configuration import validate_deployment_version
from permissions.models import CurrentUser
from permissions.operations import authorization_metadata, operations_scope, resource_read_tenant


@pytest.fixture(autouse=True)
def grants(mocker):
    mocker.patch(
        "permissions.operations.has_permission", side_effect=lambda roles, permission: bool(set(roles) & {"OPS", "SU"})
    )


@pytest.mark.parametrize("role", ["ADMIN", "DEV", "USER", "ASSET_OWNER", "SPEED"])
def test_operations_grant_is_not_implied_by_business_roles(role):
    with pytest.raises(HTTPException) as error:
        operations_scope(CurrentUser("actor", "a", role))
    assert error.value.status_code == 403


@pytest.mark.parametrize("roles", [("OPS",), ("DEV", "OPS"), ("ADMIN", "OPS")])
def test_operations_is_tenant_scoped_for_every_ordinary_union(roles):
    user = CurrentUser("actor", "a", roles[0], roles=roles)
    assert operations_scope(user) == "a"
    assert operations_scope(user, "a") == "a"
    with pytest.raises(HTTPException) as error:
        operations_scope(user, "b", "ops.configuration:delete")
    assert error.value.status_code == 403


@pytest.mark.parametrize("action", ["read", "create", "update", "delete"])
def test_su_has_same_operations_actions_across_tenants(action):
    user = CurrentUser("actor", "a", "SU")
    assert operations_scope(user, "b", f"ops.configuration:{action}") == "b"
    assert operations_scope(user) is None
    assert authorization_metadata(user)["scope"] == "all_tenants"


def test_retired_deployment_mode_is_not_silently_elevated():
    with pytest.raises(ValueError):
        validate_deployment_version("speed")
    assert validate_deployment_version("full") == "full"


@pytest.mark.parametrize(
    "roles, query, tenant",
    [
        (("OPS",), b"", "a"),
        (("OPS",), b"tenant_id=a", "a"),
        (("DEV", "OPS"), b"", None),
        (("DEV", "OPS"), b"tenant_id=a", "a"),
        (("ADMIN", "OPS"), b"tenant_id=a", None),
        (("DEV",), b"tenant_id=a", None),
    ],
)
def test_resource_reads_use_the_inventory_grant(mocker, roles, query, tenant):
    mocker.patch("permissions.operations.get_current_user_context", return_value=("actor", "a", roles))
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer token")], "query_string": query})
    assert resource_read_tenant(request, shared=True) == tenant


@pytest.mark.parametrize("query", [b"tenant_id=b", b"tenant_id=b&tenant_id=a"])
def test_resource_inventory_rejects_foreign_tenant_targets(mocker, query):
    mocker.patch("permissions.operations.get_current_user_context", return_value=("actor", "a", ("OPS",)))
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer token")], "query_string": query})
    with pytest.raises(HTTPException) as error:
        resource_read_tenant(request)
    assert error.value.status_code == 403
