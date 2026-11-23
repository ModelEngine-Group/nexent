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
