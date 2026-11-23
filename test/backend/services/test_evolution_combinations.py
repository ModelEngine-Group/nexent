# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from contracts.errors.exceptions import AppException
from contracts.evolution import DevelopmentExperimentRequest
from management.services.evaluation import experiments


def part(kind, cid, eid):
    return {"candidate_type": kind, "candidate_id": cid, "experiment_id": eid}


def request(*parts):
    return DevelopmentExperimentRequest(agent_id=8, version_no=1, evaluator_id=7, case_ids=[2], request_id="joined",
                                        candidate_type="combination", components=list(parts))


@pytest.mark.parametrize("parts", [
    [part("prompt", 2, 4)], [part("prompt", 2, 4), part("prompt", 3, 5)],
    [part("skill_step", 2, 4), part("skill_step", 2, 8)],
    [part("tool_set", 2, 4), part("skill_step", 2, 4)],
])
def test_cannot_overlay_competing_revisions_or_reference_the_same_experiment(parts):
    with pytest.raises(ValidationError):
        request(*parts)


@pytest.mark.parametrize("problem", ["other_agent", "unrelated_candidate", "unpaired", "bad_receipt", "drift", "same_skill"])
def test_ineligible_single_experiments_cannot_be_combined(monkeypatch, problem):
    req = request(part("skill_discovery", 2, 4), part("skill_step", 3, 5))
    def plan(tenant, eid, active_only):
        assert active_only
        selected = req.components[eid - 4]
        old = req.model_dump(exclude={"components"})
        old.update(candidate_type=selected.candidate_type, candidate_id=selected.candidate_id)
        if eid == 5 and problem == "other_agent":
            old["agent_id"] = 19
        if eid == 5 and problem == "unrelated_candidate":
            old["candidate_id"] = 100
        return {"request": old, "snapshots":{"base":"base","result":"result"}, "cases":{"2":"case"}}

    def trials(tenant, eid):
        rows = [{"case_id":2, "variant":arm, "status":"pass", "receipt_id":arm,
                 "result":{"case_digest":"case", "snapshot_digest":arm}} for arm in ("base", "result")]
        if problem == "unpaired":
            return rows[:1]
        if problem == "bad_receipt":
            rows[0]["result"]["case_digest"] = "changed"
        return rows

    async def local_io(name, fn, *args):
        return fn(*args)

    monkeypatch.setattr(experiments, "_io", local_io)
    monkeypatch.setattr(experiments.jobs, "read_plan", plan)
    monkeypatch.setattr(experiments.jobs, "trials", trials)
    monkeypatch.setattr(experiments, "read_bound_skill_candidate", lambda *args: {"instance_id": 6 if problem == "same_skill" else args[-1]})
    monkeypatch.setattr(experiments, "_snapshot", AsyncMock(side_effect=lambda req, tenant, user, arm: arm))
    monkeypatch.setattr(experiments, "snapshot_digest", lambda arm: "different" if problem == "drift" else arm)
    with pytest.raises(AppException):
        asyncio.run(experiments._check_components(req, "tenant", "editor"))


def test_four_arm_report_keeps_missing_single_and_joint_regression(monkeypatch):
    parts = [part("prompt", 1, 10), part("tool_set", 3, 12)]
    arms = ["base", "only_a", "only_b", "result"]
    rows = [{"case_id": cid, "variant": arm, "status": status, "result": {}}
            for cid, scores in enumerate([("fail","fail","fail","pass"), ("pass","pass","pass","fail"),
                                          ("fail","pass","fail","pass"), ("pass","pass",None,"pass")], 1)
            for arm, status in zip(arms, scores) if status is not None]
    monkeypatch.setattr(experiments.jobs, "scope", lambda *args: {
        "agent_id":8, "version_no":1, "components":parts, "regression_cases":{"2":{}, "4":{}},
        "planned_cases":["1","2","3","4"], "planned_arms": arms})
    monkeypatch.setattr(experiments.jobs, "trials", lambda *args: rows)
    monkeypatch.setattr(experiments, "require_business_agent_edit", lambda *args: None)
    report = experiments.experiment_report("tenant", "editor", 6)
    assert report["components"] == parts
    assert report["valid_quartets"] == 3 and report["valid_pairs"] == 4
    assert report["combination_counts"] == {"joint_only":1, "lost_single_pass":1, "retained_single_gain":1, "inconclusive":1}
    assert report["pairs"][2]["combination"]["combined_vs_a"] == "regressed"
    assert report["fixed_regression"] == {"case_ids":[2,4], "failed":[2], "incomplete":[4]}
