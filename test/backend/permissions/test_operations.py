# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Operations grants and scope are independent of business permissions."""

import pytest
from fastapi import HTTPException

from contracts.configuration import validate_deployment_version
from permissions.models import CurrentUser
from permissions.operations import authorization_metadata, operations_scope


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
