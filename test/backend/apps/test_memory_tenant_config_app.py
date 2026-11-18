# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from management.api.memory import memory_config


@pytest.fixture
def api(monkeypatch):
    role = Mock(return_value={"user_roles": ["ADMIN"]})
    persistence = Mock()
    context = Mock(return_value=("u", "owned-tenant", ("ADMIN",)))
    monkeypatch.setattr(memory_config, "get_current_user_id", lambda *_: ("u", "owned-tenant"))
    monkeypatch.setattr(memory_config, "get_user_tenant_by_user_id", role)
    monkeypatch.setattr(memory_config, "get_current_user_context", context)
    monkeypatch.setattr(memory_config, "upsert_single_tenant_setting", persistence)
    monkeypatch.setattr(memory_config, "tenant_memory_enabled", lambda tenant_id: tenant_id != "owned-tenant")
    app = FastAPI()
    app.include_router(memory_config.router)
    return TestClient(app), role, persistence, context


def test_admin_reads_saved_false_and_updates_current_tenant(api):
    client, _, save, _ = api
    path = "/memory/config/tenant-switch"
    assert client.get(path).json() == {"enabled": False, "can_edit": True}
    response = client.put(path, json={"enabled": True, "tenant_id": "another-tenant"})
    assert response.status_code == 200
    save.assert_called_once_with("owned-tenant", "TENANT_MEMORY_SWITCH", "Y", "u")


def test_non_admin_cannot_persist_tenant_memory_setting(api):
    client, role, save, context = api
    role.return_value = {"user_roles": ["USER"]}
    context.return_value = ("u", "owned-tenant", ("USER",))
    path = "/memory/config/tenant-switch"
    assert client.get(path).json()["can_edit"] is False
    assert client.put(path, json={"enabled": True}).status_code == 403
    save.assert_not_called()


def test_tenant_memory_setting_requires_boolean(api):
    client, _, save, _ = api
    assert client.put("/memory/config/tenant-switch", json={"enabled": "false"}).status_code == 422
    save.assert_not_called()


def test_tenant_memory_write_keeps_admin_role_bound_to_its_tenant(api):
    client, previous_role_lookup, save, context = api
    # The ID-only route lookup would still return owned-tenant.
    # The authenticated membership now pairs ADMIN with the new tenant.
    context.return_value = ("u", "new-tenant", ("ADMIN",))
    response = client.put(
        "/memory/config/tenant-switch",
        json={"enabled": False},
        headers={"Authorization": "Bearer session"},
    )

    assert response.status_code == 200
    context.assert_called_once_with("Bearer session")
    previous_role_lookup.assert_not_called()
    save.assert_called_once_with("new-tenant", "TENANT_MEMORY_SWITCH", "N", "u")
