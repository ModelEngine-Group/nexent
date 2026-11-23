# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
from unittest.mock import Mock

import pytest
from contracts.errors.exceptions import AppException
from contracts.new_skill_candidates import SkillSuccess
from management.services.evaluation import new_skill_candidates as candidates
from management.services.evaluation import new_skill_evidence as evidence


def test_common_steps_only_retains_ordered_observations():
    assert evidence.common_steps([["a", "b", "c", "d"], ["a", "x", "c", "d"], ["a", "d"]]) == ["a", "d"]
    source = SkillSuccess(case_id=1, outcomes=[{"step": "record", "excerpt": "tracked"}])
    case = {"digest": "case", "task": {"expected": "tracked"}}
    trial = {
        "receipt_id": "original",
        "status": "pass",
        "result": {
            "case_digest": "case",
            "answer": "tracked",
            "judgment": {"status": "pass"},
            "tool_use": {"status": "pass", "sequence": ["read_skill_md", "search"]},
        },
    }
    assert evidence.observed_steps(source, trial, case) == ["tool:search", "outcome:record"]
    for override in (
        {"answer": "tracked tracked"},
        {"case_digest": "wrong"},
        {"tool_use": {"status": "fail"}},
    ):
        with pytest.raises(AppException):
            evidence.observed_steps(source, {**trial, "result": {**trial["result"], **override}}, case)


def test_overlapping_observations_cannot_be_used_as_two_steps():
    record = SkillSuccess(
        case_id=1,
        outcomes=[{"step": "one", "excerpt": "review record"}, {"step": "two", "excerpt": "record"}],
    )
    case = {"digest": "case", "task": {"expected": "review record"}}
    trial = {
        "receipt_id": "pass",
        "status": "pass",
        "result": {"case_digest": "case", "judgment": {"status": "pass"}, "answer": "review record"},
    }
    with pytest.raises(AppException, match="overlap"):
        evidence.observed_steps(record, trial, case)


def test_generated_guide_rechecks_order_variables_private_examples_and_tool_grants():
    brief = dict(
        name="intake",
        steps=["outcome:receive", "outcome:archive"],
        parameters=["record id"],
        skip_when="unconfirmed",
    )
    feedback = dict(brief=brief, private_marks=[evidence.private_mark("Cloud Customer")])
    header = "---\nname: intake\ndescription: verify intake\n---\n"
    body = "receive, then archive. Use record id. Skip if unconfirmed."
    assert candidates._validate_package({"SKILL.md": header + body}, feedback)[0] == "verify intake"
    for invalid in (
        body + " CLOUD   CUSTOMER",
        body.replace("archive", ""),
        body.replace("unconfirmed", "confirmed"),
        body.replace("record id", "ID"),
        body.replace("receive, then archive", "archive, then receive"),
    ):
        with pytest.raises(AppException):
            candidates._validate_package({"SKILL.md": header + invalid}, feedback)
    with pytest.raises(AppException):
        candidates._validate_package(
            {"SKILL.md": header.replace("name: intake", "name: intake\nallowed-tools: [x]") + body}, feedback
        )
    marks = evidence.identifier_marks("Case 1234567 for info@example.com")
    for leaked in ("user INFO@example.COM", "case 1234567"):
        with pytest.raises(AppException):
            evidence.check_private(leaked, marks)


async def stream(events):
    for event in events:
        yield "data: " + json.dumps(event) + "\n\n"


@pytest.mark.asyncio
async def test_stream_discards_rolled_back_files_and_refuses_partial_artifacts():
    actions = [
        {"type": "model_attempt_control", "attempt_id": "first", "phase": "begin"},
        {"type": "file_content", "path": "references/old.md", "content": "superseded"},
        {"type": "model_attempt_control", "attempt_id": "first", "phase": "rollback"},
        {"type": "skill_body", "content": "current"},
        {"type": "done"},
    ]
    assert await candidates.collect_files(stream(actions)) == {"SKILL.md": "current"}
    for invalid in (
        actions[:-1],
        [actions[0], *actions[-2:]],
        [{"type": "file_content", "path": "references/../x.md", "content": "x"}, *actions[-2:]],
        [actions[-2], {"type": "error"}],
    ):
        with pytest.raises(AppException):
            await candidates.collect_files(stream(invalid))


def test_generation_denies_other_creator_before_inspecting_evidence(monkeypatch):
    monkeypatch.setattr(
        candidates.jobs, "read_handoff", lambda *args: {"method": "S3", "creator_id": "alice"}
    )
    reader = Mock()
    monkeypatch.setattr(candidates.jobs, "read_plan", reader)
    with pytest.raises(AppException):
        candidates._authorized_feedback("tenant", "bob", 1)
    reader.assert_not_called()


def test_confirmation_measures_delivery_and_checks_actual_use_and_correct_skip():
    from contracts.confirmation import ConfirmationPolicy
    from management.services.evaluation.confirmation_results import arm_measurement, comparison_summary

    policy = ConfirmationPolicy(
        minimum_valid_pairs=2,
        minimum_valid_percent=100,
        family_minimums={"business": 2},
        minimum_quality_gain_pp=1,
    )

    def measure(arm, grade, expected, reads):
        from management.services.evaluation.experiments import judge_skill_selection

        data = {
            "judgment": {"status": grade},
            "new_skill_trial": {"arm": arm, "name": "intake"},
            "selection": judge_skill_selection(expected, reads),
        }
        return arm_measurement(grade, data, require_selection=True)

    available = measure("result", "pass", ["intake"], {"intake": 1})
    skipped = measure("result", "pass", [], {})
    solved = measure("base", "pass", ["intake"], {})
    failed = measure("base", "fail", ["intake"], {})

    def compare(pairs):
        return comparison_summary(
            policy, [("business", old, new) for old, new in pairs], require_new_skill=True
        )

    control = compare([(solved, available), (solved, skipped)])
    assert (
        solved["status"] == "pass" and control["improved"] == 0 and control["failures"] == ["quality_target"]
    )
    assert compare([(failed, available), (solved, skipped)])["quality_gain_pp"] == 50
    assert compare([(failed, available), (solved, available)])["decision"] == "insufficient"
    assert compare([(failed, skipped), (solved, available)])["decision"] == "insufficient"
    assert (
        compare([(failed, available), (solved, measure("result", "pass", [], {"intake": 1}))])["decision"]
        == "failed"
    )
