# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
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
