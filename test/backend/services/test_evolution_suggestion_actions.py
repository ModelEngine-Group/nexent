# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.services.evaluation import skill_candidates, suggestion_actions


@pytest.fixture
def target():
    return {"agent_id": 7, "version_no": 2, "experiment_id": 8, "suggestion_id": 10,
            "skill_id": 3, "skill_name": "handovers", "released_guide_candidate_id": None, "candidate_id": 11,
            "base_digest": "a" * 64, "feedback": {"method": "S2", "feedback_id": 15,
                                                  "edit": {"old": "Do {task}", "new": "Review {task}"}}}


@pytest.mark.parametrize(("agent_edit", "skill_edit"), [(True, True), (True, False), (False, True), (False, False)])
def test_independent_receipt_permissions(monkeypatch, target, agent_edit, skill_edit):
    def check(allowed):
        if not allowed:
            raise AppException(ErrorCode.COMMON_FORBIDDEN)

    monkeypatch.setattr(suggestion_actions, "receipt_target", lambda *args: target)
    monkeypatch.setattr(suggestion_actions, "require_business_agent_edit", lambda *args: check(agent_edit))
    monkeypatch.setattr(suggestion_actions, "authorize_step_revision", lambda *args: check(skill_edit))
    actions = suggestion_actions.suggestion_actions("tenant", "actor", 1, 2)
    assert ("compare" in actions) is agent_edit
    assert ("edit" in actions) is skill_edit
    assert "handovers" not in str(actions) and "Do {task}" not in str(actions)


def test_manual_revision_preserves_source_ownership_and_package(monkeypatch, target):
    original = {"SKILL.md": b"---\nname: handovers\n---\nDo {task}\nKeep record format.\n",
                "references/style.md": b"Preserve", "scripts/run.py": b"# unchanged"}
    skill = {"name": "handovers", "skill_id": 3}
    checks = []
    monkeypatch.setattr(skill_candidates, "authorize_step_revision", lambda *args: checks.append(args) or skill)
    monkeypatch.setattr(skill_candidates, "load_skill_package", lambda *args: original)
    stored = {}

    def store_package(tenant, skill_id, files):
        assert (tenant, skill_id) == ("tenant", 3)
        stored["files"] = files
        return "b" * 64

    def store_candidate(tenant, actual, user, base, result, feedback):
        assert (tenant, actual, user, base, result) == ("tenant", skill, "editor", "a" * 64, "b" * 64)
        stored["feedback"] = feedback
        return 27

    monkeypatch.setattr(skill_candidates, "store_skill_package", store_package)
    monkeypatch.setattr(skill_candidates, "store_skill_candidate", store_candidate)
    assert skill_candidates.revise_skill_step_candidate("tenant", "editor", target, "Confirm {task}") == {"candidate_id": 27}
    assert len(checks) == 2
    assert stored["files"] == {**original, "SKILL.md": original["SKILL.md"].replace(b"Do {task}", b"Confirm {task}")}
    assert stored["feedback"]["parent_candidate_id"] == 11 and stored["feedback"]["receipt_suggestion_id"] == 10
    assert stored["feedback"]["feedback_id"] == 15
    assert target["feedback"]["edit"]["new"] == "Review {task}"


@pytest.mark.parametrize("replacement", [" ", "Do {task}", "Review {task}", "Confirm {wrong_field}"])
def test_invalid_revision_never_records_candidate(monkeypatch, target, replacement):
    monkeypatch.setattr(skill_candidates, "authorize_step_revision", lambda *args: {"skill_id": 3})
    monkeypatch.setattr(skill_candidates, "load_skill_package", lambda *args: {"SKILL.md": b"---\nname: x\n---\nDo {task}"})
    monkeypatch.setattr(skill_candidates, "store_skill_package", lambda *args: pytest.fail("invalid revision stored"))
    with pytest.raises(AppException, match="proposed passage|placeholders"):
        skill_candidates.revise_skill_step_candidate("tenant", "editor", target, replacement)
