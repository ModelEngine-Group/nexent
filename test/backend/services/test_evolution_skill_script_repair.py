# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import copy
import json
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from contracts.errors.exceptions import AppException
from contracts.evolution import ToolUseRule
from contracts.skill_script_repair import ScriptDraftRequest, ScriptRepairFeedback
from management.services.evaluation import skill_script_repairs as repairs
from nexent.core.agents.resources.replay_tools import argument_digest


SOURCE = "# weekly\r\n@staticmethod\r\ndef summarize(value):\r\n    return value\r\n\r\nOTHER = 5\r\n"
REPLACEMENT = "def summarize(value):\n    return value.upper()"


def test_script_expectation_is_opt_in_and_requires_bundled_inputs():
    assert "expected_script_stdout" not in ToolUseRule(name="lookup").model_dump()
    rule = {"name": "run_skill_script", "arguments": {"skill_name": "weekly", "script_path": "scripts/weekly.py"},
            "expected_script_stdout": ""}
    assert ToolUseRule(**rule).expected_script_stdout == ""
    for update in [{"name": "lookup"}, {"min_calls": 0}, {"arguments": {}},
                   {"arguments": {**rule["arguments"], "source": "workspace"}},
                   {"arguments": {**rule["arguments"], "params": "'"}}]:
        with pytest.raises(ValidationError):
            ToolUseRule(**{**rule, **update})


def test_replace_function_keeps_other_files_outside_edit_and_preserves_newlines():
    assert repairs.replace_function(SOURCE, "summarize", REPLACEMENT) == SOURCE.replace(
        "    return value\r\n", "    return value.upper()\r\n")
    for edit in [REPLACEMENT.replace("value):", "value, extra):"), REPLACEMENT + "\nEXTRA = 1",
                 "async " + REPLACEMENT, "@staticmethod\n" + REPLACEMENT, "def summarize(value):\n    return value",
                 "def summarize(", REPLACEMENT.replace("summarize(", "other(")]:
        with pytest.raises(AppException):
            repairs.replace_function(SOURCE, "summarize", edit)


@pytest.fixture
def script_feedback(monkeypatch):
    name, path = "weekly", "scripts/weekly.py"
    files = {"SKILL.md": b"guide", path: SOURCE.encode(), "requirements.txt": b"frozen==1"}
    cases, trials = {}, {}
    script = sha256(files[path]).hexdigest()
    for cid, params, expected, output, status in [(1, "abc", "ABC", "abc", "fail"), (2, "123", "123", "123", "pass")]:
        rule = {"name": "run_skill_script", "arguments": {"params": params, "skill_name": name, "script_path": path},
                "expected_script_stdout": expected}
        cases[cid] = {"digest": str(cid), "task": {"query": str(cid), "attachments": [], "tool_use": {"rules": [rule]}}}
        process = {"skill": argument_digest(name), "path": argument_digest(path), "image": "sha256:" + "a"*64,
                   "argv": argument_digest([params]), "script": script, "exit_code": 0, "stdout": sha256(output.encode()).hexdigest(),
                   "call": 1, "input_matches": True, "stdout_matches": status == "pass"}
        trials[cid] = {"case_id": cid, "variant": "base", "receipt_id": f"receipt{cid}", "status": status,
                       "result": {"snapshot_digest": "base", "case_digest": str(cid), "tool_use": {"status": status,
                                  "issues": [], "script_evidence": [process]}}}
    repeat = copy.deepcopy(trials[1])
    repeat["receipt_id"] = "repeated"
    request = ScriptRepairFeedback(skill_id=9, failure_case_id=1, protection_case_id=2, repeat_experiment_id=21,
                                  function="summarize", goal="Preserve all weekly rows", share_script_examples=True)
    saved = {}
    def store(tenant, user, eid, feedback):
        saved.update(feedback)
        return 32
    plan = {"request": {"agent_id": 7, "version_no": 1, "candidate_type": "baseline"}, "cases": {"1":"1","2":"2"},
            "snapshots": {"base": "base"}}
    monkeypatch.setattr(repairs, "snapshot_digest", lambda _: "base")
    monkeypatch.setattr(repairs, "require_business_agent_edit", Mock())
    monkeypatch.setattr(repairs, "require_development_sources", Mock())
    monkeypatch.setattr(repairs.jobs, "read_plan", lambda *args: plan)
    monkeypatch.setattr(repairs.jobs, "trials", lambda tenant, eid: [repeat] if eid == 21 else trials.values())
    monkeypatch.setattr(repairs, "get_development_case", lambda *args: cases[args[-1]])
    monkeypatch.setattr(repairs, "query_skill_instances_by_agent_id", lambda *args: [{"skill_id": 9, "skill_instance_id": 4, "enabled": True}])
    monkeypatch.setattr(repairs, "read_bound_skills", lambda *args: [{"instance_id": 4}])
    monkeypatch.setattr(repairs, "skill_execution_revision", lambda *args: "pin")
    monkeypatch.setattr(repairs, "get_skill_by_id", lambda *args: {"name": name})
    monkeypatch.setattr(repairs, "feedback_skill_files", lambda *args: files)
    monkeypatch.setattr(repairs.jobs, "store_handoff", store)
    monkeypatch.setattr(repairs.jobs, "read_handoff", lambda *args: saved)
    monkeypatch.setattr(repairs, "_editable_skill", lambda *args: {"name": name})
    return request, SimpleNamespace(resource=SimpleNamespace(agent_id=7, version_no=1,
                   skill_refs=[SimpleNamespace(instance_id=4, revision="pin")])), repeat, files, saved


def test_handoff_separates_agent_feedback_and_maintainer_draft(script_feedback, monkeypatch):
    request, spec, _, files, saved = script_feedback
    assert repairs._freeze("tenant", "editor", 20, request, spec) == 32
    assert saved["source_case_ids"] == [1, 2] and saved["repeat_receipt"] == "repeated"
    author = Mock(return_value=json.dumps({"replacement": REPLACEMENT}))
    monkeypatch.setattr(repairs, "invoke_candidate_model", author)
    model = repairs.draft_script("tenant", "maintainer", 32, ScriptDraftRequest(model_id=5))
    manual = repairs.draft_script("tenant", "maintainer", 32, ScriptDraftRequest(replacement=REPLACEMENT))
    assert model == manual and "+    return value.upper()" in model["diff"]
    assert len(model["draft_digest"]) == 64 and model["source_digest"] != model["draft_digest"]
    assert files["scripts/weekly.py"] == SOURCE.encode() and author.call_count == 1
    prompt = json.loads(author.call_args.kwargs["user_prompt"])
    assert prompt["failure"]["exit_code"] == 0 and not prompt["failure"]["output_matched"]
    assert prompt["protection"]["output_matched"] and "receipt1" not in author.call_args.kwargs["user_prompt"]
    files["requirements.txt"] = b"frozen==2"
    with pytest.raises(AppException, match="package changed"):
        repairs.draft_script("tenant", "maintainer", 32, ScriptDraftRequest(model_id=5))
    assert author.call_count == 1


@pytest.mark.parametrize("field", ["argv", "stdout", "script", "image", "exit_code", "input_matches"])
def test_changed_repeat_never_creates_repair_feedback(script_feedback, field):
    request, spec, repeat, _, saved = script_feedback
    repeat["result"]["tool_use"]["script_evidence"][0][field] = False if field == "input_matches" else "different"
    with pytest.raises(AppException):
        repairs._freeze("tenant", "editor", 20, request, spec)
    assert not saved


def test_script_evaluation_never_falls_back_to_host_execution(tmp_path):
    from nexent.core.agents.resources.replay_tools import ReplayToolRecorder
    from nexent.core.tools.run_skill_script_tool import RunSkillScriptTool

    tool = RunSkillScriptTool(local_skills_dir=str(tmp_path), authorized_skill_names=["weekly"], tenant_id="org")
    tool.skill_manager = Mock()
    recorder = ReplayToolRecorder(None, {tool.name: ["script_path"]}, watch_skill_process=True)
    recorder.bind(tool, tool.name)
    result = tool.forward(skill_name="weekly", script_path="scripts/weekly.py")
    assert "Docker sandbox" in result
    tool.skill_manager.run_skill_script.assert_not_called()
    assert "skill_process" not in recorder.receipt()["calls"][0]

def test_script_gain_needs_same_input_state_image_and_build():
    from management.services.evaluation.tool_use import observed_script, script_effect

    build = {"base": "old", "result": "new", "image": "image", "name": "weekly", "path": "scripts/weekly.py"}
    process = {"input_matches": True, "script": "old", "image": "image", "skill": argument_digest("weekly"),
               "path": argument_digest("scripts/weekly.py"), "argv": "args", "exit_code": 0, "stdout_matches": None,
               "files_match": False, "files": {"initial": "state", "changes": {}}}
    def observed(arm, **changes):
        return observed_script({"tool_use": {"script_evidence": [{**process, **changes}]}}, build, arm)

    base = observed("base")
    current = observed("result", script="new", files_match=True)
    assert script_effect(base, current) == "corrected"
    assert script_effect(observed("base", files_match=True), current) == "protected"
    for changes in ({"image": "wrong"}, {"script": "old"}, {"input_matches": False}, {"files_match": None},
                    {"files": {"initial": "other"}}, {"argv": "other"}, {"files_match": False}):
        assert script_effect(base, observed("result", **{"script": "new", "files_match": True, **changes})) is None


def test_output_state_distinguishes_rewrites_deletions_and_incomplete_evidence():
    from nexent.core.agents.resources.replay_scripts import file_changes

    old = [5, {"a": ["content", 20, 1, 33188]}]
    replaced = [6, {"a": ["content", 30, 3, 33188]}]
    assert file_changes(old, old)["changes"] == {}
    assert file_changes(old, replaced)["changes"] == {"a": "content"}
    assert file_changes(old, [6, {}])["changes"] == {"a": None}
    assert file_changes(old, [6, old[1]]) is None
    assert file_changes(None, replaced) is None
