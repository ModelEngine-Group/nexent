# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import pytest


@pytest.mark.case_id("EVOLUTION-PAIR-REPORT-D1-001")
@pytest.mark.stage("D1")
def test_grade_and_compare(monkeypatch):
    from contracts.agentos import EvaluationAgentResult
    from contracts.evolution import DevelopmentExperimentRequest
    from management.services.evaluation import experiments as service

    request = DevelopmentExperimentRequest(request_id="d1", agent_id=1, version_no=1, candidate_id=1,
        candidate_type="prompt", evaluator_id=42, case_ids=list(range(1, 7)))
    rule = {"evaluator_type": "code", "name": "deliver", "pass_threshold": 1.0,
            "code": "def evaluate(query, expected, actual, runtime_events):\n    return {'score': int(expected == actual)}"}
    job = {"plan": {"evaluator": rule}, "tenant_id": "tenant", "created_by": "editor"}
    partial = EvaluationAgentResult(answer="y", events=[
        {"type": "final_answer", "answer_phase": "delta", "content": "y"},
        {"type": "final_answer", "invocation_id": "subtask", "content": "y"},
    ])
    assert service._grade(request, job, {"query": "deliver", "expected": "y"}, partial)["status"] == "missing_evidence"
    rows = []
    for case_id, answers in enumerate([("n","y"),("y","n"),("y","y"),("n","n"),(None,"y"),("y","pending")], 1):
        for variant, answer in zip(("base", "result"), answers):
            if answer == "pending":
                grade = {"status": "pending"}
            else:
                obs = EvaluationAgentResult(answer=answer or "", events=[{"type":"final_answer"}] if answer else [])
                grade = service._grade(request, job, {"query": "deliver", "expected": "y"}, obs)
            rows.append({"case_id":case_id, "variant":variant, "status":grade["status"], "result":grade})
    monkeypatch.setattr(service, "require_business_agent_edit", lambda *args: None)
    monkeypatch.setattr(service.jobs, "scope", lambda *args: {"agent_id":1,"version_no":1})
    monkeypatch.setattr(service.jobs, "trials", lambda *args: rows)
    report = service.experiment_report("tenant", "editor", 8)
    assert report["total_pairs"] == 6 and report["valid_pairs"] == 4 and report["status"] == "running"
    assert report["counts"] == dict(improved=1, regressed=1, both_pass=1, both_fail=1, inconclusive=2)
    assert report["pairs"][2]["result"]["result"]["score"] == 0
    assert report["pairs"][5]["base"]["status"] == "missing_evidence"
    assert "valid_triplets" not in report
    for row in rows:
        row["result"]["skill"] = {"guide_reads": 0 if row["case_id"] == 2 else 1}
    rows.extend({"case_id": i, "variant": "no_skill", "status": status, "result": {}}
                for i, status in enumerate(["fail", "pass", "invalid", "fail", "pass", "pass"], 1))
    report = service.experiment_report("tenant", "editor", 8)
    assert report["valid_pairs"] == 4 and report["valid_triplets"] == 3 and report["verified_guide_pairs"] == 2
    assert report["pairs"][1]["skill_vs_absent"] == {"base":"both_fail", "result":"improved"}
    assert report["pairs"][3]["skill_vs_absent"] == {"base":"inconclusive", "result":"inconclusive"}
    rows[:] = [dict(case_id=i, variant="base", status=status,
                    result={"selection": service.judge_skill_selection(["guide"], reads)})
               for i, (status, reads) in enumerate([("pass", {}), ("pass", {"guide": 1}),
                                                     ("invalid", {"other": 1})], 1)]
    report = service.experiment_report("tenant", "editor", 8)
    assert report["total_tasks"] == 3 and report["valid_baselines"] == 2
    assert report["valid_pairs"] == report["total_pairs"] == 0
    assert report["selection_counts"] == {"base": {"missed": 1, "hit": 1}}
    from contracts.agentos import ReplayToolObservation
    from contracts.evolution import ToolUseExpectation
    from management.services.evaluation.tool_use import judge_tool_use
    rule = ToolUseExpectation(rules=[{"name": "read", "min_calls": 1, "max_calls": 1}]).model_dump()
    receipt = ReplayToolObservation(registered=["read"], complete=True, calls=[])
    tool_grade = judge_tool_use(rule, receipt)
    delivered = service._grade(request, job, {"query": "deliver", "expected": "y"},
                               EvaluationAgentResult(answer="y", events=[{"type": "final_answer"}]))
    assert delivered["status"] == "pass" and tool_grade["issues"][0]["reason"] == "too_few"
    assert judge_tool_use(rule, None)["status"] == "missing_evidence"
    removed = ReplayToolObservation(registered=[], complete=True, calls=[])
    assert judge_tool_use(rule, removed, absent={"read"})["status"] == "fail"
    skip = ToolUseExpectation(rules=[{"name": "read", "min_calls": 0, "max_calls": 0}]).model_dump()
    assert judge_tool_use(skip, removed, absent={"read"})["status"] == "pass"
    assert judge_tool_use(skip, removed)["status"] == "missing_evidence"
    arms = ["base", "only_a", "only_b", "result"]
    scope = {"agent_id": 1, "version_no": 1, "planned_cases": ["1", "2", "3"], "planned_arms": arms,
             "regression_cases": {"2": {}, "3": {}}, "components": [{"experiment_id": 4}, {"experiment_id": 5}]}
    monkeypatch.setattr(service.jobs, "scope", lambda *args: scope)
    rows[:] = [
        {"case_id": cid, "variant": arm, "status": outcome, "result": {}}
        for cid, scores in enumerate([("fail", "fail", "fail", "pass"), ("pass", "pass", "pass", "fail"),
                                      ("pass", "pass", None, "pass")], 1)
        for arm, outcome in zip(arms, scores) if outcome is not None
    ]
    report = service.experiment_report("tenant", "editor", 8)
    assert report["valid_quartets"] == 2
    assert report["combination_counts"] == {"joint_only": 1, "lost_single_pass": 1, "inconclusive": 1}
    assert report["fixed_regression"]["failed"] == [2]
    assert report["fixed_regression"]["incomplete"] == [3]

    from contracts.replay_files import FileStateReceipt
    from management.services.evaluation.replay_dialogue import judge_file_state
    from nexent.core.agents.resources.replay_files import files_digest

    criteria = {"target_case_ids": [1], "metric": "tasks_fixed", "minimum": 1}
    scope.update(screening=criteria, cancelled=False, components=None, planned_cases=["1","2"], planned_arms=["base","result"])
    rule = {**job["plan"]["evaluator"], "version_no":1, "evaluator_id":42}
    fixed_rule = {**rule, "version_no": 3, "evaluator_id": 43}
    fixed = {"2":{"scoring":{"evaluator":fixed_rule, "language":"en", "judge_model_id":None}}}
    scope["regression_cases"] = fixed
    plan = {"request":{"candidate_type":"prompt","screening":criteria}, "evaluator":rule, "regression_cases":fixed,
            "cases":{"1":"target","2":"fixed"},"snapshots":{"base":"old","result":"new"}}
    monkeypatch.setattr(service.jobs, "read_plan", lambda *args: plan)
    rows.clear()
    for case_id in (1,2):
        for arm, snapshot in plan["snapshots"].items():
            job = {"plan":plan,"case_id":case_id,"created_by":"editor","tenant_id":"tenant"}
            obs = EvaluationAgentResult(answer="n" if (case_id,arm) == (1,"base") else "y",
                                       events=[{"type":"final_answer"}])
            grade = service._grade(request, job, {"query":"deliver","expected":"y"}, obs)
            rows.append({"case_id":case_id,"variant":arm,"status":grade["status"],"receipt_id":f"{case_id}-{arm}",
                         "result":{"judgment":grade,"case_digest":plan["cases"][str(case_id)],"snapshot_digest":snapshot,
                                   "evaluator_id":grade["evaluator_id"],"evaluator_version":grade["evaluator_version"]}})
    report = service.experiment_report("tenant", "editor", 9)
    assert report["screening"]["status"] == "eligible" and report["screening"]["gain"] == 1
    files = {"locked.txt":"keep"}
    receipt = FileStateReceipt(initial_digest=files_digest(files), files=files, writes_by_tool={"create_file":["locked.txt"]},
                               bound=["create_file"], writes=["locked.txt"], complete=True)
    from types import SimpleNamespace
    state = judge_file_state({"adapter":"text-files-v1","initial":files,"expected":files,"protected":["locked.txt"]},
                             [SimpleNamespace(file_state=receipt)])
    assert state["status"] == "fail"
    rows[-1]["status"] = state["status"]
    rows[-1]["result"]["file_state"] = state
    decision = service.experiment_report("tenant", "editor", 9)["screening"]
    assert decision["status"] == "failed" and decision["failures"] == {"forbidden_action":[2],"protection_failed":[2]}

    plan["request"]["suggestion_target_case_id"] = 2
    assert service.experiment_report("tenant", "editor", 9)["screening"]["failures"]["suggestion_target_failed"] == [2]
    del plan["request"]["suggestion_target_case_id"]

    # Reuse the same business task and fixed regression rubric in all four arms.
    from copy import deepcopy
    protected = rows[-1]
    protected["status"] = "pass"
    del protected["result"]["file_state"]
    parts = [{"experiment_id": 4, "candidate_type": "prompt", "candidate_id": 5},
             {"experiment_id": 5, "candidate_type": "tool_set", "candidate_id": 8}]
    scope.update(planned_arms=arms, components=parts)
    plan["request"].update(candidate_type="combination", components=parts)
    for arm in ("only_a", "only_b"):
        plan["snapshots"][arm] = arm
        for base in [r for r in rows if r["variant"] == "base"]:
            single = deepcopy(base)
            single.update(variant=arm, receipt_id=f"{base['case_id']}-{arm}")
            single["result"]["snapshot_digest"] = arm
            rows.append(single)
    assert service.experiment_report("tenant", "editor", 9)["screening"]["status"] == "eligible"
    single = next(row for row in rows if row["variant"] == "only_b" and row["case_id"] == 1)
    single["status"] = single["result"]["judgment"]["status"] = "pass"
    decision = service.experiment_report("tenant", "editor", 9)["screening"]
    assert decision["status"] == "failed" and decision["failures"] == {"redundant_combination": [1]}
