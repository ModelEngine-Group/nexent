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

@pytest.mark.parametrize("old,new,gain", [
    ("wrong", "correct_skip", 1), ("missed", "hit", 1), ("hit", "hit", 0),
])
def test_discovery_measures_choice_separately_from_delivery(old, new, gain):
    plan, pairs = fixture("skill_choices_fixed")
    plan["request"]["candidate_type"] = "skill_discovery"
    for arm, choice in (("base", old), ("result", new)):
        trial = pairs[1][arm]
        trial.update(status="pass")
        trial["result"].update(selection={"outcome": choice}, judgment={"status": "pass"})
    decision = screen_development(plan, pairs, cancelled=False)
    assert decision["gain"] == gain
    assert decision["status"] == ("eligible" if gain else "failed")
    del pairs[1]["base"]["result"]["selection"]
    assert screen_development(plan, pairs, cancelled=False)["missing"] == {"missing_skill_selection": [1]}
    with pytest.raises(ValidationError):
        DevelopmentExperimentRequest(request_id="scope", agent_id=1, version_no=1, candidate_id=2,
                                     candidate_type="prompt", case_ids=[1, 2], evaluator_id=7,
                                     screening=plan["request"]["screening"])


def test_screen_measures_value_relative_to_both_single_revisions():
    from copy import deepcopy
    plan, pairs = fixture()
    plan["request"].update(candidate_type="combination", components=[
        {"candidate_type": "prompt", "candidate_id": 5}, {"candidate_type": "skill_step", "candidate_id": 7}])
    for arm in ("only_a", "only_b"):
        plan["snapshots"][arm] = arm
        for pair in pairs.values():
            pair[arm] = deepcopy(pair["base"])
            pair[arm]["result"]["snapshot_digest"] = arm
    def reads(arm, count):
        pairs[1][arm]["result"]["skills"] = [
            {"candidate_id": 8, "guide_reads": 1}, {"candidate_id": 7, "guide_reads": count}]
    reads("result", 1)
    reads("only_a", 0)
    assert screen_development(plan, pairs, cancelled=False)["failures"] == {"redundant_combination": [1]}
    reads("only_a", 1)
    assert screen_development(plan, pairs, cancelled=False)["status"] == "eligible"
    pairs[1]["only_a"]["result"]["judgment"]["status"] = pairs[1]["only_a"]["status"] = "pass"
    assert "redundant_combination" in screen_development(plan, pairs, cancelled=False)["failures"]
    pairs[1]["result"]["result"]["judgment"]["status"] = pairs[1]["result"]["status"] = "fail"
    assert screen_development(plan, pairs, cancelled=False)["failures"]["lost_single_pass"] == [1]
    del pairs[1]["only_b"]["receipt_id"]
    assert screen_development(plan, pairs, cancelled=False)["missing"] == {"unverified_trials": [1]}


def test_combination_token_target_compares_against_each_single_revision():
    from copy import deepcopy
    plan, pairs = fixture("input_token_reduction_pct")
    plan["request"].update(candidate_type="combination", components=[
        {"candidate_type": "prompt", "candidate_id": 5}, {"candidate_type": "tool_set", "candidate_id": 7}])
    for arm in ("only_a", "only_b"):
        plan["snapshots"][arm] = arm
        for pair in pairs.values():
            pair[arm] = deepcopy(pair["result"])
            pair[arm]["result"].update(snapshot_digest=arm, reported_step_input_tokens=85)
    assert screen_development(plan, pairs, cancelled=False)["status"] == "eligible"
    pairs[1]["only_b"]["result"]["reported_step_input_tokens"] = None
    assert screen_development(plan, pairs, cancelled=False)["missing"] == {"missing_component_tokens": [1]}
    pairs[1]["only_b"]["result"]["reported_step_input_tokens"] = 78
    assert screen_development(plan, pairs, cancelled=False)["failures"] == {"redundant_combination": [1]}

def test_another_improvement_cannot_hide_a_failed_suggestion_target():
    from copy import deepcopy

    plan, pairs = fixture()
    plan["request"].update(suggestion_id=9, suggestion_target_case_id=3)
    plan["request"]["screening"]["target_case_ids"].append(3)
    plan["cases"]["3"] = "suggestion"
    pairs[3] = deepcopy(pairs[1])
    for row in pairs[3].values():
        row["status"] = row["result"]["judgment"]["status"] = "fail"
        row["result"]["case_digest"] = "suggestion"
    decision = screen_development(plan, pairs, cancelled=False)
    assert decision["gain"] == 1 and decision["status"] == "failed"
    assert decision["failures"] == {"suggestion_target_failed": [3]}
