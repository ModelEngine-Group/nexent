# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.errors.exceptions import AppException, SnapshotCompilationError
from contracts.releases import PromotionRequest, RollbackRequest
from management.services.evaluation import releases, skill_candidates


async def inline_io(name, fn, *args):
    return fn(*args)


@pytest.mark.asyncio
async def test_rollback_pauses_on_resource_compilation_failure(monkeypatch):
    request = RollbackRequest(expected_version=3, reason="restore files")
    monkeypatch.setattr(releases, "_io", inline_io)
    target = dict(new_version=3, agent_id=7, base_version=2, language="en", rollback_at=None)
    monkeypatch.setattr(releases.releases, "rollback_target", Mock(return_value=target))
    prepare = AsyncMock(side_effect=SnapshotCompilationError("resource", OSError("missing package")))
    monkeypatch.setattr(releases, "prepare_evaluation_snapshot", prepare)
    restore = Mock(return_value={"new_sessions_paused": True})
    monkeypatch.setattr(releases.releases, "restore", restore)
    assert (await releases.rollback("tenant", "owner", 8, request))["new_sessions_paused"]
    restore.assert_called_once_with("tenant", "owner", 8, request, False)
    assert prepare.await_args.args[0].version_no == 2


@pytest.mark.asyncio
async def test_conflicting_digest_rejected_even_for_repeated_promotion(monkeypatch):
    monkeypatch.setattr(releases, "_io", inline_io)
    repeated = {"new_version": 2}
    monkeypatch.setattr(
        releases.releases,
        "prepare",
        Mock(return_value=({"version_no": 1, "digest": "a" * 64}, repeated, None)),
    )
    verify = AsyncMock()
    monkeypatch.setattr(releases, "verified_recipe", verify)
    valid = PromotionRequest(expected_version=1, reason="confirmed", candidate_digest="a" * 64)
    assert await releases.promote("tenant", "owner", 2, valid) == repeated
    with pytest.raises(AppException):
        await releases.promote("tenant", "owner", 2, valid.model_copy(update={"candidate_digest": "b" * 64}))
    verify.assert_not_awaited()


def test_feedback_reads_published_skill_and_rejects_missing_binding(monkeypatch):
    binding = {"name": "meeting", "release_package": {"digest": "a" * 64}}
    rows = Mock(return_value=[binding])
    shared = Mock()
    pinned = Mock(return_value={"SKILL.md": b"published"})
    monkeypatch.setattr(skill_candidates, "read_bound_skills", rows)
    monkeypatch.setattr(skill_candidates, "capture_skill_files", shared)
    monkeypatch.setattr(skill_candidates, "released_skill_files", pinned)
    assert skill_candidates.feedback_skill_files("tenant", "meeting", (2, 3)) == pinned.return_value
    pinned.assert_called_once_with("tenant", 2, 3, binding)
    rows.return_value = []
    with pytest.raises(AppException):
        skill_candidates.feedback_skill_files("tenant", "meeting", (2, 3))
    shared.assert_not_called()


def test_changed_shared_metadata_aborts_publication():
    session = Mock()
    row = dict(instance_id=7, name="meeting", description="keep", config={"mode": "full"})
    pins = [{"row": row, "skill_id": 8}]
    binding = dict(skill_instance_id=7, skill_id=8, config_values={"mode": "full"}, enabled=True)
    skill = SimpleNamespace(skill_id=8, skill_name="meeting", skill_description="keep", config_values={})
    session.scalar.return_value = skill
    releases.releases._validate_skill_sources(session, "tenant", [binding], pins)
    skill.skill_description = "changed"
    with pytest.raises(AppException):
        releases.releases._validate_skill_sources(session, "tenant", [binding], pins)


@pytest.mark.parametrize(
    ("state", "message"),
    [
        ({"independent": "passed"}, "等待发布"),
        ({"independent": "insufficient"}, "未达到发布条件"),
        ({"new_version": 3}, "本租户智能体 #7 发布 V3"),
        ({"new_version": 3, "rollback_at": "now"}, "已回退"),
        ({"new_version": 3, "disabled": True}, "已紧急停用"),
    ],
)
def test_submitter_receipt_tracks_release_state(state, message):
    from management.db.conversation.suggestions import _status_reply

    session = Mock()
    row = dict(
        suggestion_id=11,
        agent_id=7,
        experiment_id=4,
        new_version=None,
        lock_id=5,
        independent=None,
        disabled=False,
        rollback_at=None,
        stopped=False,
    )
    session.execute.return_value.mappings.return_value.all.return_value = [{**row, **state}]
    actual = _status_reply(
        session, {"tenant": "tenant", "owner": "submitter", "cid": 8}, "S-11", lambda zh, en: zh
    )
    assert message in actual


def tool_comparison(base_names, result_names):
    def prepared(arm, names):
        check = SimpleNamespace(arm=arm, removed=["analysis"])
        context = [{"type": "tool", "content": {"name": name}} for name in names]
        options = SimpleNamespace(context_items=context)
        return SimpleNamespace(tool_set_check=check, resource=SimpleNamespace(evaluation_options=options))

    return {"base": prepared("base", base_names), "result": prepared("result", result_names)}


def test_promotion_requires_exact_agreement_between_confirmed_catalogs():
    valid = tool_comparison(["analysis", "read"], ["read"])
    assert releases._confirmed_tool_exclusions(valid) == ("analysis",)
    for after in (["analysis", "read"], [], ["read", "write"]):
        with pytest.raises(AppException):
            releases._confirmed_tool_exclusions(tool_comparison(["analysis", "read"], after))
    valid["result"].tool_set_check.removed = ["read"]
    with pytest.raises(AppException):
        releases._confirmed_tool_exclusions(valid)
