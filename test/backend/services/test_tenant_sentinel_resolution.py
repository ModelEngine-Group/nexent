# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Gateway tenant_id sentinel must be resolved against real user_tenant rows."""

from unittest.mock import patch

import pytest

from contracts.constants.constants import (
    ASSET_OWNER_TENANT_ID,
    DEFAULT_TENANT_ID,
)
from management.services.permission.identity import session as session_module


def _identity(user_id="su-user", tenant_id=DEFAULT_TENANT_ID, roles=("SU",)):
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": roles[0],
        "roles": list(roles),
        "kind": "session",
    }


def _record(tenant_id=""):
    return {"tenant_id": tenant_id}


def test_gateway_sentinel_resolves_to_real_tenant(mocker):
    mocker.patch.object(session_module, "_gateway_identity", return_value=_identity())
    mocker.patch.object(
        session_module, "get_user_tenant_by_user_id",
        return_value=_record(tenant_id="real-tenant-1"))

    user_id, tenant_id = session_module._resolve_session_user()

    assert user_id == "su-user"
    assert tenant_id == "real-tenant-1"


def test_gateway_sentinel_falls_back_to_first_active_when_row_still_empty(mocker):
    mocker.patch.object(session_module, "_gateway_identity", return_value=_identity())
    mocker.patch.object(
        session_module, "get_user_tenant_by_user_id", return_value=_record())
    mocker.patch.object(
        session_module, "resolve_tenant_id_from_user_tenant_record",
        return_value="first-active-tenant")

    _, tenant_id = session_module._resolve_session_user()

    assert tenant_id == "first-active-tenant"


def test_real_tenant_passes_through_unchanged(mocker):
    mocker.patch.object(
        session_module, "_gateway_identity",
        return_value=_identity(tenant_id="real-tenant-1"))

    _, tenant_id = session_module._resolve_session_user()

    assert tenant_id == "real-tenant-1"


def test_asset_owner_sentinel_also_resolves(mocker):
    mocker.patch.object(
        session_module, "_gateway_identity",
        return_value=_identity(
            tenant_id=ASSET_OWNER_TENANT_ID, roles=("ASSET_OWNER",)))
    mocker.patch.object(
        session_module, "get_user_tenant_by_user_id",
        return_value=_record(tenant_id="asset-owner-tenant"))

    _, tenant_id = session_module._resolve_session_user()

    assert tenant_id == "asset-owner-tenant"


def test_context_fn_resolves_sentinel(mocker):
    mocker.patch.object(session_module, "_gateway_identity", return_value=_identity())
    mocker.patch.object(
        session_module, "get_user_tenant_by_user_id",
        return_value=_record(tenant_id="real-tenant-1"))

    user_id, tenant_id, roles = session_module.get_current_user_context()

    assert user_id == "su-user"
    assert tenant_id == "real-tenant-1"
    assert "SU" in roles
