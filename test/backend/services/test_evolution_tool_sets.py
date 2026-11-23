# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
from types import SimpleNamespace

import pytest

from contracts.errors.exceptions import AppException
from contracts.evolution import ToolSetProposal
from management.services.evaluation import tool_set_candidates as sets
from nexent.core.agents.resources.replay_tools import ReplayToolRecorder, record_tool_catalog


def test_model_input_probe_watches_only_target_names_in_root_instructions_and_definitions():
    root = object()
    recorder = ReplayToolRecorder(root, {}, ["read", "read_log"])
    observer = SimpleNamespace(replay_tool_recorder=recorder)
    assert record_tool_catalog(observer, object(), "jiuwen", [], [], []) is None
    probe = record_tool_catalog(observer, root, "jiuwen", [], [], [])
    probe.observe_model_input([{"role": "user", "content": "read private input"},
                               {"role": "system", "content": "can_read has another name"},
                               SimpleNamespace(semantic_role="system", content_parts=[{"text": "Use read_log."}])],
                              [SimpleNamespace(name="read")])
    assert recorder.catalog["instruction_mentions"] == ["read_log"]
    assert recorder.catalog["native_definitions"] == ["read"]
    assert recorder.catalog["model_inputs"] == 1
    assert "private input" not in str(recorder.catalog)


def test_only_observed_optional_tools_are_removed_from_the_current_scope(monkeypatch):
    request = ToolSetProposal(failure_case_ids=[1], protection_case_ids=[2])
    candidates = []
    rules = {
        1: [{"name": name, "min_calls": 0, "max_calls": 0}
            for name in ["needed", "file", "lookup", "platform"]],
        2: [{"name": "needed", "min_calls": 1, "max_calls": 1}],
    }
    rows = [{"case_id": cid, "receipt_id": f"receipt-{cid}", "variant": "base", "status": status,
             "result": {"case_digest": str(cid), "tool_use": {"status": status, "issues": [
                 {"reason": "too_many", "tool": rule["name"]} for rule in rules[cid]
             ] if cid == 1 else []}}} for cid, status in [(1, "fail"), (2, "pass")]]
    monkeypatch.setattr(sets.jobs, "trials", lambda *args: rows)
    monkeypatch.setattr(sets, "get_development_case", lambda *args: {
        "digest": str(args[-1]), "task": {"tool_use": {"rules": rules[args[-1]]}}})
    monkeypatch.setattr(sets, "require_business_agent_edit", lambda *args: None)

    def store(tenant, agent, version, user, baseline, variants, *, field):
        assert (tenant, agent, version, user, field) == ("tenant", 4, 1, "editor", "agent.tools")
        assert json.loads(baseline)["baseline"] == "digest"
        candidates.extend(variants)
        return [10, 11, 12]

    monkeypatch.setattr(sets, "store_prompt_candidates", store)
    source = {"baseline": "digest", "selectable": ["file", "lookup", "needed", "unused"]}
    variants = sets.generate_tool_sets("tenant", "editor", 22, request, source, 4, 1)["variants"]
    assert [v["removed"] for v in variants] == [[], ["file"], ["lookup"], ["file", "lookup"]]
    assert variants[-1]["retained"] == ["needed", "unused"]
    for _, feedback in candidates:
        assert [e["receipt_id"] for e in feedback["evidence"]] == ["receipt-1", "receipt-2"]
    rows[0]["result"]["case_digest"] = "another-revision"
    with pytest.raises(AppException):
        sets.generate_tool_sets("tenant", "editor", 22, request, source, 4, 1)
    assert len(candidates) == 3


def test_tool_set_cannot_add_a_tool_or_outlive_its_baseline(monkeypatch):
    spec = SimpleNamespace(resource=SimpleNamespace(evaluation_options=SimpleNamespace(
        context_items=[{"type": "tool", "content": {"name": n}} for n in ("read", "list", "internal")])))
    monkeypatch.setattr(sets, "selectable_tool_names", lambda *args: {"read", "list"})
    source = sets.encode({"baseline": "snapshot", "selectable": ["list", "read"]})
    row = {"source_text": source, "base_digest": sets.text_digest(source)}
    monkeypatch.setattr(sets, "get_prompt_candidate", lambda *args, **kwargs: row)

    def retain(names):
        row["result_text"] = sets.encode({"retained": names})
        row["result_digest"] = sets.text_digest(row["result_text"])

    retain(["read"])
    assert sets.resolve_tool_set("tenant", 4, 1, 11, spec, "snapshot") == ["list"]
    with pytest.raises(AppException):
        sets.resolve_tool_set("tenant", 4, 1, 11, spec, "new-snapshot")
    for invalid in (["read", "internal"], ["list", "read"]):
        retain(invalid)
        with pytest.raises(AppException):
            sets.resolve_tool_set("tenant", 4, 1, 11, spec, "snapshot")
