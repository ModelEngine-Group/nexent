# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""CHAT-MODEL-CONTROLS-D2-002: actual API permissions and safe model errors."""

import pytest

from model_controls.api import api_fixture

pytestmark = [pytest.mark.case_id("CHAT-MODEL-CONTROLS-D2-002"), pytest.mark.stage("D2")]


@pytest.fixture
def api(monkeypatch):
    return api_fixture(monkeypatch)


def test_model_permission_and_tenant_preflight(api):
    for path, denied in [("/api/agent/nl2agent/run", "no-agent-create"), ("/api/skills/nl2skill/run", "no-skill-create")]:
        assert api.post(path, api.payload(path), token=None).status_code == 401
        assert api.post(path, api.payload(path), token=denied).status_code == 403
        assert api.calls == []
    for path in ["/api/agent/run", "/api/agent/nl2agent/run", "/api/skills/nl2skill/run"]:
        for label, status, code in [("foreign", 404, "model_not_available"), ("unavailable", 409, "model_unavailable"),
                                    ("embedding", 400, "model_type_invalid")]:
            model_id = api.records[label]["model_id"]
            api.configured.append(model_id)
            response = api.post(path, api.payload(path, model_id=model_id))
            assert response.status_code == status, response.text
            assert response.json()["detail"] == {"code": code}
            assert "fixture.invalid" not in response.text and "api_key" not in response.text
        missing = max(r["model_id"] for r in api.records.values()) + 1
        api.configured.append(missing)
        assert api.post(path, api.payload(path, model_id=missing)).json()["detail"] == {"code": "model_not_available"}
    assert api.calls == []
    plain_id = api.records["plain"]["model_id"]
    api.configured = [api.records["effort"]["model_id"]]
    assert api.post("/api/agent/run", api.payload("/api/agent/run", model_id=plain_id)).status_code == 403
    response = api.post("/api/skills/nl2skill/run", api.payload("/api/skills/nl2skill/run", model_id=plain_id,
                                                            model_parameter_preferences={str(plain_id): {"enable_thinking": True, "reasoning_effort": "xhigh"}}))
    assert response.status_code == 422 and api.calls == []
    valid = api.records["effort"]["model_id"]
    assert api.post("/api/skills/nl2skill/run", api.payload("/api/skills/nl2skill/run", model_id=valid)).status_code == 200
    assert len(api.calls) == 1
