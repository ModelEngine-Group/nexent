"""CHAT-MODEL-CONTROLS-D2-001: actual HTTP DTO and compatibility contract."""

import json

import pytest

from model_controls.api import EFFORTS, api_fixture

pytestmark = [pytest.mark.case_id("CHAT-MODEL-CONTROLS-D2-001"), pytest.mark.stage("D2")]


@pytest.fixture
def api(monkeypatch):
    return api_fixture(monkeypatch)


@pytest.mark.parametrize("path", ["/api/agent/run", "/api/agent/nl2agent/run", "/api/skills/nl2skill/run"])
def test_http_control_intents(api, path):
    def submit(**values):
        response = api.post(path, api.payload(path, **values))
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        return json.loads(response.text.removeprefix("data: ").strip())

    original = submit()
    assert (original["enabled"], original["effort"], original["temperature"], original["top_p"]) == (True, "medium", 0.43, 0.78)
    assert "generation_config" not in api.calls[-1]
    assert submit(generation_config={}) == original
    preserved = {"history": [{"role": "user", "content": "Prior fixture turn"}],
                 "minio_files": [{"object_name": "fixture-attachment", "description": "Fixture text"}]}
    if "skill" in path:
        preserved.update(language="en", draft_snapshot={"name": "fixture_skill", "content": "Existing fixture"})
    submit(**preserved)
    for key, value in preserved.items():
        assert api.calls[-1][key] == value
    if "nl2" in path:
        assert submit(generation_config=None, model_id=None) == original
    for effort in EFFORTS + ["auto"]:
        result = submit(model_id=api.records["effort"]["model_id"], generation_config={"deep_thinking": True, "thinking_effort": effort})
        assert result["effort"] == ("medium" if effort == "auto" else effort)
        assert api.calls[-1]["generation_config"]["thinking_effort"] == effort
    result = submit(generation_config={"deep_thinking": False, "thinking_effort": "xhigh"})
    assert result["enabled"] is False and result["effort"] is None
    # A partial effort does not create a missing enablement field in the DTO.
    submit(generation_config={"thinking_effort": "high"})
    assert "deep_thinking" not in api.calls[-1]["generation_config"]
    budget_id = api.records["budget"]["model_id"]
    if path == "/api/agent/run":
        api.configured.append(budget_id)
    for budget in [0, 1024, 8192]:
        result = submit(model_id=budget_id, generation_config={"deep_thinking": True, "reasoning_budget_tokens": budget})
        assert result["effort"] is None and result["budget"] == (budget or None)
    if "nl2" in path:
        saved = {"schema_version": 3, "mode": "skill_create" if "skill" in path else "agent_create",
                 "model_id": api.records["effort"]["model_id"],
                 "generation_config": {"deep_thinking": True, "thinking_effort": "xhigh"}}
        assert submit(workbench_config=saved)["effort"] == "xhigh"
    else:
        assert submit(model_id=budget_id, reasoning_budget_tokens=1024)["budget"] == 1024
    assert all("temperature" not in (r.get("generation_config") or {}) for r in api.calls)
    assert all("top_p" not in (r.get("generation_config") or {}) for r in api.calls)


@pytest.mark.parametrize("path", ["/api/agent/run", "/api/agent/nl2agent/run", "/api/skills/nl2skill/run"])
def test_http_rejects_invalid_overlays_before_execution(api, path):
    invalid = [{"thinking_effort": "invalid"}, {"deep_thinking": True, "thinking_effort": "high", "reasoning_budget_tokens": 2000},
               {"deep_thinking": True, "reasoning_budget_tokens": 1024}, {"deep_thinking": True, "thinking_effort": "xhigh"}]
    if "nl2" in path:
        invalid += [{"deep_thinking": None}, {"thinking_effort": None}, {"reasoning_budget_tokens": None},
                    {"deep_thinking": "false"}, {"temperature": 73}, {"top_p": 90}]
    before = len(api.calls)
    for index, overlay in enumerate(invalid):
        model_id = api.records["plain" if index == 3 else "effort"]["model_id"]
        if path == "/api/agent/run":
            api.configured.append(model_id)
        response = api.post(path, api.payload(path, model_id=model_id, generation_config=overlay))
        assert response.status_code == 422, response.text
    budget_id = api.records["budget"]["model_id"]
    api.configured.append(budget_id)
    for budget in [1, 8193, -1, 2.5]:
        response = api.post(path, api.payload(path, model_id=budget_id,
                                             generation_config={"deep_thinking": True, "reasoning_budget_tokens": budget}))
        assert response.status_code == 422, response.text
    if "nl2" in path:
        for extra in [{"model_id": api.records["budget"]["model_id"]}, {"generation_config": {"thinking_effort": "high"}}]:
            body = api.payload(path, workbench_config={"model_id": api.records["effort"]["model_id"],
                                                      "generation_config": {"thinking_effort": "xhigh"}}, **extra)
            assert api.post(path, body).status_code == 422
    assert len(api.calls) == before
