# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant-scoped reads for routes that expose resource inventory."""

import pytest
from fastapi import HTTPException, Request

from permissions.models import CurrentUser
from permissions.resource_access import resource_read_tenant


@pytest.fixture(autouse=True)
def inventory_grant(mocker):
    mocker.patch("permissions.resource_access.has_permission", side_effect=lambda roles, permission: "OPS" in roles)


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
    mocker.patch("permissions.resource_access.get_current_user_context", return_value=("actor", "a", roles))
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer token")], "query_string": query})
    assert resource_read_tenant(request, shared=True) == tenant


@pytest.mark.parametrize("query", [b"tenant_id=b", b"tenant_id=b&tenant_id=a"])
def test_resource_inventory_rejects_foreign_tenant_targets(mocker, query):
    mocker.patch("permissions.resource_access.get_current_user_context", return_value=("actor", "a", ("OPS",)))
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer token")], "query_string": query})
    with pytest.raises(HTTPException) as error:
        resource_read_tenant(request)
    assert error.value.status_code == 403


def test_resource_read_reuses_authenticated_user(mocker):
    lookup = mocker.patch("permissions.resource_access.get_current_user_context")
    assert resource_read_tenant(None, user=CurrentUser("actor", "a", "OPS")) == "a"
    lookup.assert_not_called()
