# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest
from pydantic import ValidationError

from contracts.evolution import DevelopmentExperimentRequest
from management.utils.suggestion_intent import choose_target, future_request, intent


@pytest.mark.parametrize(("message", "expected"), [
    ("以后这个 Skill 也要保留没有负责人的待办。", "propose"),
    ("以后这个 Skill 要把负责人写成“待分配”。", "propose"),
    ("这次把漏掉的项补上。", None),
    ("刚才那条建议进展如何？", "status"),
    ("建议S-124进展怎么样？", "status"),
    ("我个人偏好，以后这个 Skill 要把结论变蓝。", None),
    ("同事说以后这个 Skill 要保留来源。", None),
    ("“以后这个 Skill 要保留来源。”", None),
    ("是否可以修改这个 Skill？", None),
    ("以后这个 Skill 有两个附件。", None),
    ("提交建议", "confirm"),
    ("算了", "cancel"),
    ("以后请列出材料来源。", "detail"),
    ("使用 Skill meeting-action-list", "target"),
    ("meeting-action-list", "target"),
    ("Please always include owners in this skill.", "propose"),
])
def test_first_party_intents(message, expected):
    assert intent(message) == expected


def test_target_must_be_unique_and_long_term_scope_excludes_current_delivery():
    skills = [{"name":"meeting-actions"}, {"name":"meeting-actions-v2"}]
    assert choose_target("优化 meeting-actions-v2 Skill", skills) == skills[1]
    assert choose_target("优化 meeting-actions 和 meeting-actions-v2", skills) is None
    assert choose_target("以后这个 Skill 要保留来源", skills) is None
    assert choose_target("以后这个 Skill 要保留来源", skills[:1]) == skills[0]
    assert future_request("这次先补上编号 123，以后这个 Skill 要保留来源。") == "以后这个 Skill 要保留来源"
    assert future_request("以后这个 Skill 要保留来源，这次先补上编号 123。") == "以后这个 Skill 要保留来源"


def test_linked_experiment_requires_target_and_protection_preserves_old_submission_digest():
    args = dict(request_id="request", agent_id=7, version_no=1, candidate_id=4, candidate_type="skill_step",
                case_ids=[3], evaluator_id=1)
    assert "suggestion_id" not in DevelopmentExperimentRequest(**args).model_dump()
    with pytest.raises(ValidationError):
        DevelopmentExperimentRequest(**args, suggestion_id=8)
    with pytest.raises(ValidationError):
        DevelopmentExperimentRequest(**{**args, "case_ids":[3, 9]}, suggestion_id=8, suggestion_target_case_id=7)
    req = DevelopmentExperimentRequest(**{**args, "case_ids":[3, 9]}, suggestion_id=8, suggestion_target_case_id=3)
    assert req.model_dump()["suggestion_id"] == 8
