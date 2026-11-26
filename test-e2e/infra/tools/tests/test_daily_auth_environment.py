# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Daily environment propagation through the product login contract."""

import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import httpx
import pytest
import yaml


AUTOMATION = Path(__file__).resolve().parents[2] / "automation"
TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION))
sys.path.insert(0, str(TOOLS))

import run_cases
from shared.auth import configured_user, request_session


@pytest.mark.asyncio
@pytest.mark.parametrize(("process_value", "expected_password"), [
    ("process-value", "process-value"),
    (None, "file-value"),
    ("", "file-value"),
])
async def test_machine_environment_password_reaches_login(
    tmp_path, monkeypatch, process_value, expected_password,
):
    config = tmp_path / "config"
    config.mkdir()
    (config / "users.yaml").write_text(yaml.safe_dump({
        "users": [{
            "id": "tenant_a_admin",
            "username": "fixture@example.invalid",
            "password_env_key": "SYNTHETIC_PASSWORD",
        }],
    }), encoding="utf-8")
    (config / "daily.env").write_text("", encoding="utf-8")
    (config / "secrets.env").write_text("SYNTHETIC_PASSWORD=file-value\n", encoding="utf-8")
    (config / "environment.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.delenv("SYNTHETIC_PASSWORD", raising=False)
    if process_value is not None:
        monkeypatch.setenv("SYNTHETIC_PASSWORD", process_value)

    env = run_cases.machine_environment(tmp_path, tmp_path)
    with patch.dict(os.environ, env, clear=True):
        record, password = configured_user("tenant_a_admin", home=tmp_path)
        requests = []

        def login_response(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"access_token": "synthetic-token"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(login_response),
            base_url="http://fixture.invalid",
        ) as api:
            await request_session(api, record["username"], password)

    assert requests == [{"email": "fixture@example.invalid", "password": expected_password}]
