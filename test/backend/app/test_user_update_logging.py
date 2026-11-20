# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ordinary user-update logs contain an action, without credential-derived values."""

import importlib.util
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Keep database/service initialization outside this HTTP logging regression.
with pytest.MonkeyPatch.context() as imports:
    for name in ("management.services.permission.identity.session", "management.services.permission.identity.users",
                 "management.services.permission.identity.roles", "management.db.identity.user_tenant",
                 "management.services.monitor.audit", "permissions.role_assignment"):
        imports.setitem(sys.modules, name, MagicMock())
    path = Path(__file__).resolve().parents[3] / "backend/management/api/identity/user.py"
    spec = importlib.util.spec_from_file_location("_user_logging_regression", path)
    user = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(user)


def test_user_update_log_does_not_include_identity_values(mocker, caplog):
    mocker.patch.object(user, "get_current_user_context", return_value=("private-actor", "tenant", ("ADMIN",)))
    update = mocker.patch.object(user, "update_user_for_requester", new_callable=AsyncMock,
                               return_value={"user_id": "private-target", "username": "renamed"})
    audit = mocker.patch.object(user, "record_security_event")
    app = FastAPI()
    app.include_router(user.router)
    with caplog.at_level(logging.INFO, logger="user_app"), TestClient(app) as client:
        response = client.put("/users/private-target", json={"username": "renamed"},
                              headers={"Authorization": "Bearer private-credential"})
    assert response.status_code == 200
    assert response.json()["data"]["username"] == "renamed"
    records = [record for record in caplog.records if record.name == "user_app"]
    assert len(records) == 1
    assert records[0].getMessage() == "User account updated"
    assert not records[0].args
    assert not any(value in records[0].getMessage() for value in ("private-actor", "private-target", "private-credential"))
    update.assert_awaited_once_with("private-target", {"username": "renamed"},
        updated_by="private-actor", requester_tenant_id="tenant", requester_role=("ADMIN",))
    assert audit.call_args.kwargs["user_id"] == "private-actor"
    assert audit.call_args.kwargs["details"]["target_user_id"] == "private-target"
