# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local JWT compatibility contract against the real router and PostgreSQL."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"infra/automation"))
from local_auth_http import native_runtime, runtime, register, bearer
pytestmark=[pytest.mark.case_id("API-006"),pytest.mark.stage("D2")]

def test_session_endpoints_reject_unsigned_and_retired_refresh(runtime):
    client, auth, helpers, models = runtime
    for value in ["unsigned.claims.payload", ""]:
        current = client.get("/api/user/current_user_id",headers=bearer(value))
        assert current.status_code == 401
        assert "access_token" not in current.text
    refresh=client.post("/api/user/refresh_token",headers=bearer("unsigned.claims.payload"),json={"refresh_token":"invalid"})
    assert refresh.status_code == 401
    assert "access_token" not in refresh.text
