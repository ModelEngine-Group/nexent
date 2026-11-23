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
