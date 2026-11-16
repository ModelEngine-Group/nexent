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
    monkeypatch.setattr(memory_config, "get_current_user_id", lambda *_: ("u", "owned-tenant"))
    monkeypatch.setattr(memory_config, "get_user_tenant_by_user_id", role)
    monkeypatch.setattr(memory_config, "upsert_single_tenant_setting", persistence)
    monkeypatch.setattr(memory_config, "tenant_memory_enabled", lambda tenant_id: tenant_id != "owned-tenant")
    app = FastAPI()
    app.include_router(memory_config.router)
    return TestClient(app), role, persistence


def test_admin_reads_saved_false_and_updates_current_tenant(api):
    client, _, save = api
    path = "/memory/config/tenant-switch"
    assert client.get(path).json() == {"enabled": False, "can_edit": True}
    response = client.put(path, json={"enabled": True, "tenant_id": "another-tenant"})
    assert response.status_code == 200
    save.assert_called_once_with("owned-tenant", "TENANT_MEMORY_SWITCH", "Y", "u")


def test_non_admin_cannot_persist_tenant_memory_setting(api):
    client, role, save = api
    role.return_value = {"user_roles": ["USER"]}
    path = "/memory/config/tenant-switch"
    assert client.get(path).json()["can_edit"] is False
    assert client.put(path, json={"enabled": True}).status_code == 403
    save.assert_not_called()


def test_tenant_memory_setting_requires_boolean(api):
    client, _, save = api
    assert client.put("/memory/config/tenant-switch", json={"enabled": "false"}).status_code == 422
    save.assert_not_called()
