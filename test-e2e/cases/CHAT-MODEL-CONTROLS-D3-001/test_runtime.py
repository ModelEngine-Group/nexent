# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""CHAT-MODEL-CONTROLS-D3-001: provider wire and capacity on real runtime paths."""

import json
import pytest

from model_controls.runtime import runtime_fixture

pytestmark = [pytest.mark.case_id("CHAT-MODEL-CONTROLS-D3-001"), pytest.mark.stage("D3")]


@pytest.fixture
def runtime(monkeypatch):
    with runtime_fixture(monkeypatch) as fixture:
        yield fixture


@pytest.mark.parametrize("path,workbench", [
    ("/api/agent/run", False), ("/api/agent/run", True),
    ("/api/agent/nl2agent/run", False), ("/api/agent/nl2agent/run", True),
    ("/api/skills/nl2skill/run", False), ("/api/skills/nl2skill/run", True),
])
def test_selected_creator_runtime_wire(runtime, path, workbench):
    before = runtime.draft()
    before_models = runtime.model_records()
    response = runtime.post(path, generation={"deep_thinking": True, "thinking_effort": "xhigh"}, workbench=workbench, version_no=0)
    assert response.status_code == 200, response.text
    assert runtime.provider.wire, response.text
    wire = runtime.provider.wire[-1]
    assert wire["model"] == "fixture-selected-B"
    assert wire["path"].endswith("/selected-B/chat/completions")
    assert wire["temperature"] == (0.56 if path == "/api/agent/run" and not workbench else 0.43)
    assert wire["top_p"] == 0.78
    assert wire["reasoning_effort"] == "xhigh"
    assert "fixture_custom" in str(wire)
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert not any(event.get("type") == "error" for event in events), response.text
    assert any(event.get("type") in {"done", "complete", "run_complete", "final_answer"} for event in events), response.text
    metrics = [json.loads(event["content"]) for event in events if event.get("type") == "token_count"]
    assert metrics and metrics[-1]["context_window_tokens"] == 8000
    assert metrics[-1]["effective_input_limit_tokens"] == 7000
    assert runtime.draft()["model_ids"] == before["model_ids"]
    assert runtime.draft()["model_params_override"] == before["model_params_override"]
    assert runtime.draft()["business_logic_model_id"] == before["business_logic_model_id"]
    assert runtime.model_records() == before_models
    if workbench:
        from sqlalchemy import select
        from database.db_models import ConversationRecord
        with runtime.storage["sessions"]() as session:
            stored = session.scalar(select(ConversationRecord.workbench_config).where(
                ConversationRecord.conversation_id == int(response.headers["conversation_id"])))
            assert stored["model_id"] == runtime.models["selected-B"]
            assert stored["generation_config"]["thinking_effort"] == "xhigh"
    if path == "/api/agent/run" and not workbench:
        children = runtime.runs[-1].agent_config.worker_agents
        assert children and children[0].model_name == "business-C"
    if "nl2agent" in path:
        assert runtime.draft()["description"] == "Model controls fixture draft updated", response.text
    elif "nl2skill" in path:
        generated = "".join(event.get("content", "") for event in events if event.get("type") in {"final_answer", "skill_body"})
        assert "model_control_fixture" in generated
        assert runtime.draft() == before


def test_reasoning_variants_preserve_independent_configuration(runtime):
    original = runtime.draft()
    original_models = runtime.model_records()
    paths = [("/api/agent/run", False), ("/api/agent/run", True),
             ("/api/agent/nl2agent/run", False), ("/api/agent/nl2agent/run", True),
             ("/api/skills/nl2skill/run", False), ("/api/skills/nl2skill/run", True)]
    for path, workbench in paths:
        variants = [("selected-B", None, "medium", None),
                    ("selected-B", {"deep_thinking": False, "thinking_effort": "xhigh"}, None, None),
                    ("selected-B", {"deep_thinking": True, "thinking_effort": "auto"}, "medium", None),
                    *[("selected-B", {"deep_thinking": True, "thinking_effort": e}, e, None)
                      for e in ["none", "minimal", "low", "medium", "high", "xhigh", "max"]],
                    *[("budget-B", {"deep_thinking": True, "thinking_effort": "auto", "reasoning_budget_tokens": b}, None, b or 2048)
                      for b in [0, 1024, 8192]]]
        for label, generation, effort, budget in variants:
            before = len(runtime.provider.wire)
            response = runtime.post(path, label=label, generation=generation, workbench=workbench, version_no=0)
            assert response.status_code == 200, response.text
            # Existing title/compaction inference may use its independent default model.
            wire = [row for row in runtime.provider.wire[before:] if row["model"] == "fixture-" + label]
            assert wire, response.text
            assert all(row["model"] == "fixture-" + label for row in wire)
            root = next(m for m in runtime.runs[-1].model_config_list if m.cite_name == runtime.runs[-1].agent_config.model_name)
            assert root.reasoning_effort == effort
            assert root.reasoning_budget_tokens == budget
            assert root.top_p == 0.78
            assert all(row.get("reasoning_effort") == effort for row in wire)
            if budget is not None:
                assert all(row.get("thinking_budget") == budget for row in wire)
            else:
                assert all("thinking_budget" not in row for row in wire)
            independent = next(m for m in runtime.runs[-1].model_config_list if m.cite_name == "business-C")
            assert independent.model_name == "fixture-business-C" and independent.reasoning_effort == "high"
            assert independent.temperature == 0.43 and independent.top_p == 0.78
    assert runtime.draft()["model_ids"] == original["model_ids"]
    assert runtime.draft()["model_params_override"] == original["model_params_override"]
    assert runtime.model_records() == original_models
    from sqlalchemy import update
    from database.db_models import ModelRecord
    with runtime.storage["sessions"]() as session:
        session.execute(update(ModelRecord).where(ModelRecord.model_id == runtime.models["selected-B"]).values(
            extra_params={"enable_thinking": True, "reasoning_effort": "auto", "__custom__": {"fixture_custom": "retained"}}))
    for path, workbench in paths:
        before_wire = len(runtime.provider.wire)
        response = runtime.post(path, generation={"deep_thinking": True, "thinking_effort": "auto"}, workbench=workbench, version_no=0)
        assert response.status_code == 200
        wire = [row for row in runtime.provider.wire[before_wire:] if row["model"] == "fixture-selected-B"]
        assert wire and all("reasoning_effort" not in row for row in wire)


@pytest.mark.parametrize("path,workbench", [
    ("/api/agent/run", False), ("/api/agent/run", True),
    ("/api/agent/nl2agent/run", False), ("/api/agent/nl2agent/run", True),
    ("/api/skills/nl2skill/run", False), ("/api/skills/nl2skill/run", True),
])
def test_sampling_runtime_wire_and_persisted_intent(runtime, path, workbench):
    before_models = runtime.model_records()
    before_draft = runtime.draft()
    response = runtime.post(path, generation={"deep_thinking": False, "temperature": 0, "top_p": 0.6},
                            workbench=workbench, version_no=0)
    assert response.status_code == 200, response.text
    wire = [row for row in runtime.provider.wire if row["model"] == "fixture-selected-B"]
    assert wire, response.text
    assert all(row["temperature"] == 0 and row["top_p"] == 0.6 for row in wire)
    assert not any('"type": "error"' in line for line in response.text.splitlines())
    run = runtime.runs[-1]
    root = next(m for m in run.model_config_list if m.cite_name == run.agent_config.model_name)
    assert set(root.explicit_sampling) == {"temperature", "top_p"}
    independent = next(m for m in run.model_config_list if m.cite_name == "business-C")
    assert (independent.temperature, independent.top_p) == (0.43, 0.78)
    assert independent.explicit_sampling == []
    assert runtime.model_records() == before_models
    assert runtime.draft()["model_params_override"] == before_draft["model_params_override"]
    if workbench:
        from sqlalchemy import select
        from database.db_models import ConversationRecord
        with runtime.storage["sessions"]() as session:
            saved = session.scalar(select(ConversationRecord.workbench_config).where(
                ConversationRecord.conversation_id == int(response.headers["conversation_id"])))
            assert saved["generation_config"]["temperature"] == 0
            assert saved["generation_config"]["top_p"] == 0.6
