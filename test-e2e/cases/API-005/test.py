# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local JWT compatibility contract against the real router and PostgreSQL."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"infra/automation"))
from local_auth_http import native_runtime, runtime, register, bearer
pytestmark=[pytest.mark.case_id("API-005"),pytest.mark.stage("D2")]

def test_local_jwt_identity_and_session_without_refresh(runtime):
    client, auth, helpers, models = runtime
    data = register(client)
    token = data["session"]["access_token"]
    assert data["session"]["refresh_token"] == ""
    session = client.get("/api/user/session", headers=bearer(token))
    assert session.status_code == 200
    assert session.json()["data"]["user"]["id"] == data["user"]["id"]
    current = client.get("/api/user/current_user_info", headers=bearer(token))
    assert current.status_code == 200
    assert current.json()["data"]["user"]["tenant_id"] == "tenant-native"
    refresh = client.post("/api/user/refresh_token", headers=bearer(token),json={"refresh_token":"retired-refresh"})
    assert refresh.status_code == 401
    assert "access_token" not in refresh.text
