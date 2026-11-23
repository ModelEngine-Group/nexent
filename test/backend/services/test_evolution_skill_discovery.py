# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from hashlib import sha256
from unittest.mock import Mock

import pytest

from contracts.errors.exceptions import AppException
from contracts.errors.codes import ErrorCode
from contracts.evolution import DiscoveryExample
from infrastructure.rdb.skill_candidate_records import candidate_skill_row
from infrastructure.skill_package import encode_skill_package
from management.services.evaluation import skill_candidates
from management.services.evaluation.experiments import judge_skill_selection
from management.services.evaluation.feedback_handoff import _selection_excerpt


@pytest.mark.parametrize("expected,reads,group", [
    ([], {}, "correct_skip"), ([], {"calendar": 2}, "wrong"), (["minutes"], {}, "missed"),
    (["minutes", "summary"], {"summary": 1}, "hit"), (["minutes"], {"minutes": 1, "calendar": 1}, "wrong"),
])
def test_choice_counts_neighbor_reads_and_acceptable_alternatives(expected, reads, group):
    assert judge_skill_selection(expected, reads)["outcome"] == group


@pytest.mark.parametrize("expected,reads,group,status,excerpt", [
    (["minutes", "summary"], {"summary": 1}, "missed", "pass", "meeting"),
    (["minutes"], {"minutes": 1}, "correct", "fail", "meeting"),
    ([], {"minutes": 1}, "overused", "invalid", "meeting"),
    (["minutes"], {"minutes": 1}, "correct", "pass", "unapproved"),
])
def test_reject_wrong_handoff_evidence(expected, reads, group, status, excerpt):
    case = {"digest": "original", "task": {"query": "meeting request", "expected_skill_names": expected}}
    trial = {"status": status, "receipt_id": "receipt", "result": {"case_digest": case["digest"],
             "selection": judge_skill_selection(expected, reads)}}
    with pytest.raises(AppException):
        _selection_excerpt("minutes", group, DiscoveryExample(case_id=1, query_excerpt=excerpt), trial, case)


def test_only_approved_description_can_replace_the_bound_catalog_row():
    row = {"name": "meeting", "description": "old", "config": {"style": 1}}
    bound = {"method": "S1", "source_text": "old", "result_text": "new", "base_digest": "same", "result_digest": "same"}
    assert candidate_skill_row(row, bound, "result") == {**row, "description": "new"}
    assert candidate_skill_row(row, bound, "base") is row
    for change in ({"source_text": "outdated"}, {"result_digest": "another"}, {"result_text": ""}):
        with pytest.raises(ValueError):
            candidate_skill_row(row, {**bound, **change}, "result")


def test_permission_checked_before_and_after_rewrite(monkeypatch):
    from json import dumps
    skill = {"name": "meeting", "description": "old"}
    files = {"SKILL.md": b"untouched"}
    feedback = dict(agent_id=5, version_no=1, skill_id=4, skill_name="meeting", source_text="old", goal="better selection",
                    source_digest=sha256(encode_skill_package(files)).hexdigest(),
                    **{k: {"example_id": k} for k in ("missed", "overused", "correct")})
    denied = AppException(ErrorCode.COMMON_FORBIDDEN)
    model = Mock(return_value=dumps(dict(old="old", new="new", reason="conditions",
                                         evidence_ids=["missed", "overused", "correct"])))
    store = Mock()
    monkeypatch.setattr(skill_candidates, "feedback_skill_files", lambda *_: files)
    monkeypatch.setattr(skill_candidates, "store_skill_package", store)
    monkeypatch.setattr(skill_candidates, "invoke_chat_prompt_in_worker", model)
    monkeypatch.setattr(skill_candidates, "_editable_skill", Mock(side_effect=denied))
    with pytest.raises(AppException):
        skill_candidates.generate_skill_discovery_candidate(feedback, 1, 1, "tenant", "user")
    model.assert_not_called()
    monkeypatch.setattr(skill_candidates, "_editable_skill", Mock(side_effect=[skill, denied]))
    with pytest.raises(AppException):
        skill_candidates.generate_skill_discovery_candidate(feedback, 1, 1, "tenant", "user")
    model.assert_called_once()
    store.assert_not_called()
