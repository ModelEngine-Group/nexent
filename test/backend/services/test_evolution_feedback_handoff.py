# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
from unittest.mock import Mock

import pytest


def test_step_feedback_requires_reads_of_same_baseline_in_both_examples():
    from contracts.errors.exceptions import AppException
    from management.services.evaluation.feedback_handoff import _require_baseline_guide

    target = {"instance_id":21, "skill_id":5}
    observation = {"instance_id":21, "candidate_id":9, "variant":"base", "guide_reads":1}
    success = {"result":{"skill":observation}}
    _require_baseline_guide(target, 5, 9, [success, success])
    for changes in ({"guide_reads":0}, {"instance_id":2}, {"candidate_id":1}, {"variant":"result"}):
        with pytest.raises(AppException, match="reads"):
            _require_baseline_guide(target, 5, 9, [success, {"result":{"skill":{**observation, **changes}}}])
    with pytest.raises(AppException, match="match"):
        _require_baseline_guide(target, 6, 9, [success, success])


def test_only_recorded_development_excerpts_reach_resource_editor():
    from contracts.errors.exceptions import AppException
    from contracts.evolution import FeedbackExcerpt
    from management.services.evaluation.feedback_handoff import _approved_excerpt

    selected = FeedbackExcerpt(case_id=5, expected="unassigned", observed="named only")
    task = {"expected": "keep named and unassigned rows"}
    trial = {"status":"fail", "receipt_id":"1"*32, "result":{"answer":"Returned named only"}}
    evidence = _approved_excerpt(selected, "fail", trial, task)
    assert evidence == {"example_id": "case-5-trial-" + "1"*32, "expected":"unassigned", "observed":"named only"}
    for invalid in [dict(trial, status="invalid"), dict(trial, receipt_id=None),
                    dict(trial, result={"answer":"something else"})]:
        with pytest.raises(AppException):
            _approved_excerpt(selected, "fail", invalid, task)


def test_resource_editor_generation_uses_referenced_target_and_provenance(monkeypatch):
    from management.services.evaluation import feedback_handoff as service

    excerpts = {"failure":{"example_id":"bad", "observed":"omitted", "expected":"retained"},
                "protection":{"example_id":"good", "observed":"named", "expected":"named"}}
    monkeypatch.setattr(service, "contains_fixed_cases", lambda *args: False)
    record = {"source_case_ids":[1, 2], "method":"S2", "skill_id":84, "agent_id":45, "version_no":2, "goal":"keep all",
              "source_passage":"keep named", "source_digest":"d"*64, **excerpts}
    reader = Mock(return_value=record)
    generate = Mock(return_value={"candidate_id":13})
    monkeypatch.setattr(service.jobs, "read_handoff", reader)
    monkeypatch.setattr(service, "generate_skill_step_candidate", generate)
    assert service.generate_from_handoff("tenant","skill-editor",19,3)["candidate_id"] == 13
    reader.assert_called_once_with("tenant",19)
    request, tenant, user = generate.call_args.args
    assert request.skill_id == 84 and request.model_id == 3 and user == "skill-editor" and tenant == "tenant"
    assert generate.call_args.kwargs == {"agent_version":(45,2), "feedback_id":19, "source_digest":"d"*64}


def test_scoped_step_reads_pinned_package_and_keeps_header_and_references(monkeypatch):
    from contracts.errors.exceptions import AppException
    from contracts.evolution import LocalEditRequest
    from management.services.evaluation import skill_candidates as service

    source = {"name": "meeting-guide", "candidate_id": 87, "digest": "a" * 64}
    header = b"---\nname: meeting-guide\ndescription: Extract actions\n---\n"
    files = {"SKILL.md": header + b"Only include named tasks.", "references/actions.txt": b"Reference"}
    feedback = {"agent_id": 12, "version_no": 2, "released_guide_candidate_id": 87, "source_digest": source["digest"]}
    request = LocalEditRequest(model_id=3, goal="Include unassigned open tasks", source_passage="Only include named tasks.",
        failure={"example_id":"failure", "observed":"none", "expected":"one"},
        protection={"example_id":"protection", "observed":"one", "expected":"one"})
    authorize = Mock()
    read = Mock(return_value=(source, files))
    upload = Mock(return_value="b" * 64)
    save = Mock(return_value=17)
    edit = {"new": "Include all open tasks."}
    monkeypatch.setattr(service, "require_business_agent_edit", authorize)
    monkeypatch.setattr(service, "scoped_guide_files", read)
    monkeypatch.setattr(service, "propose_local_edit", Mock(return_value=(edit["new"], Mock(model_dump=lambda:edit))))
    monkeypatch.setattr(service, "store_new_skill_package", upload)
    monkeypatch.setattr(service, "store_scoped_skill_candidate", save)
    result = service.generate_scoped_skill_step(request, "tenant", "editor", 19, feedback)
    assert result["candidate_id"] == 17 and result["released_guide_candidate_id"] == 87
    read.assert_called_once_with("tenant", 12, 2, 87)
    assert authorize.call_count == 2
    upload.assert_called_once_with("tenant", 12, {**files, "SKILL.md":header + edit["new"].encode()})
    assert save.call_args.args[:6] == ("tenant", "editor", 12, 2, source, "b" * 64)

    upload.reset_mock()
    with pytest.raises(AppException, match="approved feedback"):
        service.generate_scoped_skill_step(request, "tenant", "editor", 19, {**feedback, "source_digest":"c" * 64})
    upload.assert_not_called()


def test_conflict_handoff_keeps_the_approved_related_clause(monkeypatch):
    from management.services.evaluation import feedback_handoff as service

    record = {
        "agent_id": 45, "version_no": 2, "method": "P3", "source_case_ids": [1, 2],
        "source_passage": "Always assign to OPS.", "related_passage": "Billing goes to FIN.",
        "source_digest": "a" * 64, "goal": "Resolve policy overlap",
        "failure": {"example_id": "bad", "observed": "OPS", "expected": "FIN"},
        "protection": {"example_id": "good", "observed": "OPS", "expected": "OPS"},
    }
    monkeypatch.setattr(service.jobs, "read_handoff", lambda *_: record)
    monkeypatch.setattr(service, "contains_fixed_cases", lambda *_: False)
    generate = Mock(return_value={"candidate_id": 13})
    monkeypatch.setattr(service, "generate_prompt_candidate", generate)
    assert service.generate_from_handoff("tenant", "editor", 19, 3)["candidate_id"] == 13
    request, _, _ = generate.call_args.args
    assert request.method == "P3" and request.related_passage == record["related_passage"]
    assert generate.call_args.kwargs == {"feedback_id": 19, "source_digest": record["source_digest"]}


@pytest.mark.parametrize("method", ["T1", "T2"])
def test_tool_handoff_requires_selection(method):
    from pydantic import ValidationError

    from contracts.evolution import FeedbackHandoffRequest

    with pytest.raises(ValidationError, match="Select the measured tool"):
        FeedbackHandoffRequest(method=method, goal="Choose the correct tool", source_passage="Default rule",
                               failure={"case_id": 1, "expected": "done", "observed": "done"},
                               protection={"case_id": 2, "expected": "done", "observed": "done"})


@pytest.mark.parametrize("gap", ["no_expectation", "not_checked", "missing_receipt", None])
def test_feedback_requires_observed_calls_in_both_tool_examples(monkeypatch, gap):
    from contracts.errors.exceptions import AppException
    from contracts.evolution import FeedbackHandoffRequest
    from management.services.evaluation import feedback_handoff as service

    name = "read_order"
    rule = {"name": name, "min_calls": 0, "max_calls": 0, "arguments": {}}
    tasks = {
        1: {"digest": "fail", "task": {"expected": "done", "tool_use": {"rules": [rule]}}},
        2: {"digest": "pass", "task": {"expected": "done", "tool_use": {"rules": [{**rule, "min_calls": 1, "max_calls": 1}]}}},
    }
    trials = [{"case_id": case, "variant": "base", "receipt_id": str(case), "status": row["digest"],
               "result": {"case_digest": row["digest"], "answer": "done", "tool_use": {"status": row["digest"],
                   "checked": [name], "sequence": [name], "issues": [{"tool": name, "reason": "too_many"}] if case == 1 else []}}}
              for case, row in tasks.items()]
    if gap == "no_expectation":
        tasks[2]["task"].pop("tool_use")
    elif gap == "not_checked":
        trials[1]["result"]["tool_use"]["checked"] = ["other_tool"]
    elif gap == "missing_receipt":
        trials[1]["result"].pop("tool_use")
    monkeypatch.setattr(service.jobs, "scope", lambda *args: {"agent_id": 7, "version_no": 1})
    monkeypatch.setattr(service.jobs, "read_plan", lambda *args: {})
    monkeypatch.setattr(service.jobs, "trials", lambda *args: trials)
    monkeypatch.setattr(service, "require_business_agent_edit", Mock())
    monkeypatch.setattr(service, "require_development_sources", Mock())
    monkeypatch.setattr(service, "get_development_case", lambda *args: tasks[args[-1]])
    monkeypatch.setattr(service, "published_business_agent", lambda *args: {"prompt": "Use the lookup on all orders."})
    request = FeedbackHandoffRequest(method="T1", tool_name=name, goal="Skip unnecessary calls",
        source_passage="Use the lookup on all orders.", failure={"case_id": 1, "expected": "done", "observed": "done"},
        protection={"case_id": 2, "expected": "done", "observed": "done"})
    if gap:
        with pytest.raises(AppException, match="verified behavior on both tasks"):
            service._prepare_handoff("tenant", "editor", 10, request)
    else:
        _, feedback = service._prepare_handoff("tenant", "editor", 10, request)
        assert json.loads(feedback["failure"]["tool_evidence"])["required_max"] == 0
        assert json.loads(feedback["protection"]["tool_evidence"])["calls"] == 1
