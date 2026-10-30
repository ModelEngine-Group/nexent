# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""SU-AC-01/05/07: actual HTTP routes accept one profile preference contract."""

import json
import pytest
from model_controls.api import EFFORTS, api_fixture

pytestmark = [pytest.mark.case_id("CHAT-MODEL-CONTROLS-D2-001"), pytest.mark.stage("D2")]

@pytest.fixture
def api(monkeypatch):
    return api_fixture(monkeypatch)

@pytest.mark.parametrize("path", ["/api/agent/run", "/api/agent/nl2agent/run", "/api/skills/nl2skill/run"])
def test_http_control_intents(api, path):
    model_id = api.records["effort"]["model_id"]
    def submit(values=None, **extra):
        body = api.payload(path, model_id=model_id, model_parameter_preferences={str(model_id): values or {}}, **extra)
        response = api.post(path, body)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "generation_config" not in api.calls[-1]
        return json.loads(response.text.removeprefix("data: ").strip())
    original = submit()
    assert (original["enabled"], original["effort"], original["temperature"], original["top_p"]) == (True, "medium", 0.43, 0.78)
    for effort in EFFORTS:
        assert submit({"enable_thinking": True, "reasoning_effort": effort})["effort"] == effort
    assert submit({"enable_thinking": False})["effort"] is None
    for temperature, top_p in [(0, 0), (0.7, 0.9), (2, 1)]:
        result = submit({"temperature": temperature, "top_p": top_p})
        assert (result["temperature"], result["top_p"]) == (temperature, top_p)
    preserved = {"history": [{"role": "user", "content": "Previous fixture turn"}], "minio_files": [{"object_name": "fixture-attachment"}]}
    submit(**preserved)
    for key, value in preserved.items():
        assert api.calls[-1][key] == value
    budget_id = api.records["budget"]["model_id"]
    api.configured.append(budget_id)
    for budget in [1024, 8192]:
        response = api.post(path, api.payload(path, model_id=budget_id, model_parameter_preferences={str(budget_id): {"enable_thinking": True, "reasoning_budget_tokens": budget}}))
        assert response.status_code == 200, response.text
        assert json.loads(response.text.removeprefix("data: ").strip())["budget"] == budget

@pytest.mark.parametrize("path", ["/api/agent/run", "/api/agent/nl2agent/run", "/api/skills/nl2skill/run"])
def test_http_rejects_invalid_overlays_before_execution(api, path):
    identifier = api.records["effort"]["model_id"]
    for values in [{"temperature": True}, {"top_p": 1.1}, {"reasoning_effort": "invalid"}, {"enable_thinking": False, "reasoning_effort": "high"}]:
        response = api.post(path, api.payload(path, model_id=identifier, model_parameter_preferences={str(identifier): values}))
        assert response.status_code == 422, response.text
        assert not api.calls
    for old in ["generation_config", "reasoning_effort", "reasoning_budget_tokens"]:
        response = api.post(path, api.payload(path, **{old: {}}))
        assert response.status_code == 422 and not api.calls
