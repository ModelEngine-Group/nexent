# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import pytest
from pydantic import ValidationError

from contracts.evolution import DevelopmentExperimentRequest
from management.services.evaluation.screening import screen_development


def fixture(metric="tasks_fixed"):
    criteria = {"metric":metric, "minimum":1, "target_case_ids":[1]}
    rule = {"evaluator_id":7, "version_no":2}
    plan = {"request":{"candidate_type":"prompt","screening":criteria}, "evaluator":rule,
            "cases":{"1":"target","2":"fixed"}, "snapshots":{"base":"old","result":"new"},
            "regression_cases":{"2":{"scoring":{"evaluator":{"evaluator_id":8,"version_no":3}}}}}
    pairs = {}
    for case, digest in plan["cases"].items():
        pair = {}
        for arm, snapshot in plan["snapshots"].items():
            passed = case == "2" or arm == "result"
            status = "pass" if passed else "fail"
            pair[arm] = {"receipt_id":f"{case}-{arm}", "status":status, "result":{
                "judgment":{"status":status}, "case_digest":digest, "snapshot_digest":snapshot,
                "evaluator_id":7 if case == "1" else 8, "evaluator_version":2 if case == "1" else 3,
                "reported_step_input_tokens":100 if arm == "base" else 79}}
        pairs[int(case)] = pair
    return plan, pairs


def test_screen_uses_frozen_targets_and_each_regression_rubric():
    plan, pairs = fixture()
    assert screen_development(plan, pairs, cancelled=False)["status"] == "eligible"
    assert screen_development(plan, pairs, cancelled=True)["missing"] == {"cancelled":[]}
    pairs[2]["result"]["result"]["evaluator_version"] = 2
    assert screen_development(plan, pairs, cancelled=False)["missing"] == {"unverified_trials":[2]}


@pytest.mark.parametrize("problem", ["missing_arm","missing_receipt","wrong_snapshot","wrong_case","invalid_judge"])
def test_screen_rejects_unverified_evidence(problem):
    plan, pairs = fixture()
    row = pairs[1]["base"]
    if problem == "missing_arm":
        plan["snapshots"]["no_skill"] = "absent"
    elif problem == "missing_receipt":
        row["receipt_id"] = None
    elif problem == "invalid_judge":
        row["result"]["judgment"]["status"] = "invalid"
    else:
        key = "case_digest" if problem == "wrong_case" else "snapshot_digest"
        row["result"][key] = "changed"
    decision = screen_development(plan, pairs, cancelled=False)
    assert decision["status"] == "incomplete" and 1 in decision["missing"]["unverified_trials"]


def test_known_forbidden_action_outweighs_improvement_and_missing_data():
    plan, pairs = fixture()
    pairs[1]["result"]["result"]["file_state"] = {"status":"fail","protected_writes":["locked.txt"]}
    pairs[1]["result"]["status"] = "fail"
    del pairs[1]["base"]
    del pairs[2]["base"]
    decision = screen_development(plan, pairs, cancelled=False)
    assert decision["status"] == "failed" and decision["failures"] == {"forbidden_action":[1]}
    assert decision["gain"] is None and decision["missing"] == {"unverified_trials":[1,2]}


def test_token_goal_uses_whole_task_counts_and_requires_quality():
    plan, pairs = fixture("input_token_reduction_pct")
    criteria = plan["request"]["screening"]
    criteria["minimum"] = 21
    assert screen_development(plan, pairs, cancelled=False)["status"] == "eligible"
    criteria["minimum"] = 22
    assert screen_development(plan, pairs, cancelled=False)["failures"] == {"below_target":[1]}
    pairs[1]["result"]["status"] = "fail"
    pairs[1]["result"]["result"]["judgment"]["status"] = "fail"
    pairs[1]["result"]["result"]["reported_step_input_tokens"] = None
    decision = screen_development(plan, pairs, cancelled=False)
    assert decision["failures"] == {"unfinished_token_target":[1]} and decision["missing"] == {"missing_tokens":[1]}


def test_missing_regression_and_ineffective_skill_are_reported():
    plan, pairs = fixture()
    plan["regression_cases"].clear()
    del plan["cases"]["2"]
    plan["request"]["candidate_type"] = "skill_step"
    assert screen_development(plan, pairs, cancelled=False)["missing"] == {"skill_not_read":[1],"no_fixed_regression":[]}


def test_criteria_are_optional_and_cannot_be_attached_to_another_task_or_a_baseline():
    raw = dict(request_id="test",agent_id=1,version_no=1,candidate_type="prompt",candidate_id=2,evaluator_id=7,case_ids=[1,2])
    assert "screening" not in DevelopmentExperimentRequest(**raw).model_dump()
    for ids, minimum in [([1,1],1),([1],2),([3],1)]:
        with pytest.raises(ValidationError):
            DevelopmentExperimentRequest(**raw,screening={"target_case_ids":ids,"minimum":minimum})
    with pytest.raises(ValidationError):
        DevelopmentExperimentRequest(**{**raw,"candidate_type":"baseline","candidate_id":None},
                                    screening={"target_case_ids":[1],"minimum":1})
