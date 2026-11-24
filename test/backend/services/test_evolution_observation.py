# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from concurrent.futures import Future
from types import SimpleNamespace

import pytest

def grade(evaluators, requirements, **observation):
    from management.services.evaluation import scoring

    inputs = dict(query="List actions", actual="", expected=None, runtime_events=None)
    return scoring.grade_observed_case(
        evaluators, tenant_id="test", user_id="editor", required_evidence=requirements,
        judge_model_id=1, judge_system_prompt="Grade observed actions", **(inputs | observation),
    )


def code_rule(expression):
    return {
        "name": "delivery",
        "evaluator_type": "code",
        "code": "def evaluate(query, expected, actual, runtime_events):\n    return " + expression,
        "pass_threshold": 0.8,
    }


def test_identical_rule_names_and_missing_vs_observed_empty_events():
    rules = {1: code_rule("{'score': 0}"), 2: code_rule("{'score': 1}")}
    needs = {1: {"actual"}, 2: {"runtime_events"}}
    missing = grade(rules, needs)
    assert missing[1] == {"status": "fail", "score": 0.0, "reason": ""}
    assert missing[2] == {"status": "missing_evidence", "score": None, "missing": ["runtime_events"]}
    assert grade(rules, needs, runtime_events=[])[2]["status"] == "pass"


@pytest.mark.parametrize("expression", ["{}", "{'score': True}", "{'score': 2}", "1/0", "{'score': '0'}"])
def test_broken_code_rule_cannot_be_counted_as_business_failure(expression):
    result = grade({1: code_rule(expression)}, {1: {"actual"}})[1]
    assert result["status"] == "invalid" and result["score"] is None and result["reason"]


@pytest.mark.parametrize("response", ["", "unparseable", "[]", "{}", '{"score": NaN}', '{"score": -1}'])
def test_malformed_model_results_remain_invalid(response, monkeypatch):
    from management.services.evaluation import scoring

    def submit(lane, spec, fn, *args, **kwargs):
        future = Future()
        future.set_result(fn(*args, **kwargs))
        return SimpleNamespace(future=future)

    monkeypatch.setattr(scoring.config_thread_manager, "submit", submit)
    monkeypatch.setattr(scoring, "invoke_chat_prompt_in_worker", lambda **kw: response)
    rule = {"name": "delivery", "evaluator_type": "llm", "prompt": "{{actual}}"}
    result = grade({1: rule}, {1: {"actual"}})[1]
    assert result["status"] == "invalid" and result["score"] is None and result["reason"]


def test_score_range_comes_from_the_rule_and_threshold_is_inclusive():
    rule = {**code_rule("{'score': 80}"), "score_range_max": 100, "pass_threshold": 80}
    assert grade({1: rule}, {1: {"actual"}})[1]["status"] == "pass"


@pytest.mark.parametrize("requirements", [{}, {1: set()}, {1: {"unknown"}}])
def test_unbound_rule_rejected_before_scoring(requirements):
    with pytest.raises(ValueError, match="evidence"):
        grade({1: code_rule("1/0")}, requirements)


@pytest.mark.parametrize("scope,expected", [({}, "fail"), ({"invocation_id": "child-run", "depth": 1}, "pass")])
def test_trial_does_not_use_fallback_to_pass_root_step_budget(scope, expected):
    from management.services.evaluation.experiments import _grade

    rule = code_rule("{'score': int(expected == actual)}")
    job = {"tenant_id": "tenant", "created_by": "editor", "plan": {"evaluator": rule}}
    request = SimpleNamespace(evaluator_id=3, language="en", judge_model_id=None)
    observed = SimpleNamespace(answer="FIN", events=[
        {"type": "max_steps_reached", **scope}, {"type": "final_answer", "answer_phase": "complete", "content": "FIN"},
    ])
    judgment = _grade(request, job, {"query": "Route a refund ticket", "expected": "FIN"}, observed)
    assert judgment["status"] == expected
    if expected == "fail":
        assert judgment["reason"] == "task_step_budget_exhausted"
