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
    from infrastructure import skill_package
    from infrastructure.rdb import released_skill_guides
    scoped = Mock(return_value=[{"name":"new-guide", "digest":"d"*64}])
    read_guide = Mock(return_value={"SKILL.md": b"approved guide"})
    monkeypatch.setattr(released_skill_guides,"read_released_guides",scoped)
    monkeypatch.setattr(skill_package,"load_new_skill_package",read_guide)
    assert skill_candidates.feedback_skill_files("tenant","new-guide",(2,3)) == read_guide.return_value
    read_guide.assert_called_once_with("tenant",2,"d"*64)
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
        ({"independent": "insufficient"}, "有效证据不足"),
        ({"independent": "failed"}, "未通过预设的发布条件"),
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


@pytest.mark.asyncio
async def test_missing_released_guide_prevents_rollback_to_that_version(monkeypatch):
    record = dict(new_version=4, base_version=3, agent_id=7, language="en", rollback_at=None, baseline_digest="valid")
    spec = SimpleNamespace(resource=SimpleNamespace(agent_id=7, released_skill_guides=[SimpleNamespace(digest="package")]))
    monkeypatch.setattr(releases, "_io", inline_io)
    monkeypatch.setattr(releases, "prepare_evaluation_snapshot", AsyncMock(return_value=spec))
    monkeypatch.setattr(releases, "snapshot_digest", Mock(return_value="valid"))
    monkeypatch.setattr(releases.releases, "rollback_target", Mock(return_value=record))
    read = Mock(side_effect=OSError("missing guide"))
    monkeypatch.setattr(releases, "load_new_skill_package", read)
    restore = Mock(return_value={"new_sessions_paused":True})
    monkeypatch.setattr(releases.releases, "restore", restore)
    request = RollbackRequest(expected_version=4, reason="restore")
    assert (await releases.rollback("tenant","publisher",9,request))["new_sessions_paused"]
    read.assert_called_once_with("tenant",7,"package")
    restore.assert_called_once_with("tenant","publisher",9,request,False)


def test_runtime_rejects_guide_from_another_agent_version_before_staging(monkeypatch):
    from contracts.agentos import ReleasedSkillGuide
    from infrastructure.rdb import released_skill_guides
    from runtime.agentos import prepared_skills

    wanted = ReleasedSkillGuide(name="intake", candidate_id=9, digest="b"*64)
    resource = SimpleNamespace(agent_id=2, version_no=4, released_skill_guides=[wanted])
    reader = Mock(return_value=[{**wanted.model_dump(), "digest":"a"*64}])
    monkeypatch.setattr(released_skill_guides,"read_released_guides",reader)
    mount = Mock()
    monkeypatch.setattr(prepared_skills,"_mount_guide",mount)
    with pytest.raises(ValueError, match="Agent version"):
        prepared_skills.mount_released_guides(resource,SimpleNamespace(tenant_id="tenant"),"workspace",{},"en")
    reader.assert_called_once_with("tenant",2,4)
    mount.assert_not_called()


def test_combined_skill_release_keeps_each_tested_instance_and_rollback_metadata(monkeypatch):
    from contextlib import nullcontext
    from copy import deepcopy
    from contracts.agentos import SkillExecutionBinding

    rows = [{"instance_id": i, "name": f"skill-{i}", "description": "old", "config": {}} for i in (1, 2)]
    targets = {
        41: dict(instance_id=1, method="S1", source_text="old", result_text="new", base_digest="a", result_digest="a"),
        42: dict(instance_id=2, method="S2", base_digest="b", result_digest="c"),
    }
    def revision(tenant, agent, version, row, files):
        return ({"a": "1" if row["description"] == "old" else "2", "b": "3", "c": "4"}[files["SKILL.md"]]) * 64
    prepared = {}
    for arm in ("base", "result"):
        refs = [SkillExecutionBinding(instance_id=i, package_candidate_id=i+40, package_variant=arm,
                revision=revision("t", 4, 1, {**row, "description": "new" if i==1 and arm=="result" else "old"},
                                  {"SKILL.md":targets[i+40][arm+"_digest"]})) for i,row in enumerate(rows,1)]
        resource = SimpleNamespace(skill_refs=refs, released_skill_guides=[], subagents=[], external_a2a=[])
        prepared[arm] = SimpleNamespace(resource=resource, observe_root_skill_choices=True)
    prepared["base"].model_copy = lambda **kwargs: deepcopy(prepared["base"])
    session = Mock()
    session.execute.return_value.all.return_value = [(1, 101), (2, 102)]
    monkeypatch.setattr(releases, "get_db_session", lambda: nullcontext(session))
    monkeypatch.setattr(releases, "read_bound_skills", lambda *_: rows)
    monkeypatch.setattr(releases, "read_bound_skill_candidate", lambda *args: targets[args[-1]])
    monkeypatch.setattr(releases, "load_skill_package", lambda t, skill, digest: {"SKILL.md": digest})
    monkeypatch.setattr(releases, "skill_execution_revision", revision)
    snapshot = Mock(return_value="rollback")
    monkeypatch.setattr(releases, "snapshot_digest", snapshot)
    ctx = {"agent_id":4, "version_no":1, "recipe":{"candidate_type":"combination","components":[
        {"candidate_type":"skill_discovery","candidate_id":41}, {"candidate_type":"skill_step","candidate_id":42}]}}
    pins, prompt, baseline, removed = releases._materials("t", ctx, prepared)
    assert prompt is None and baseline == "rollback" and not removed
    assert [p["result"][0] for p in pins] == ["a", "c"]
    assert pins[0]["result_description"] == "new" and "result_description" not in pins[1]
    clean = snapshot.call_args.args[0]
    assert clean.observe_root_skill_choices is None and all(r.package_candidate_id is None for r in clean.resource.skill_refs)
    targets[42]["instance_id"] = 1
    with pytest.raises(AppException):
        releases._materials("t", ctx, prepared)


def test_release_capabilities_cover_confirmed_resource_types():
    from contracts.releases import supports_release

    for kind in ("skill_new", "skill_discovery", "skill_script", "tool_mapping", "prompt", "tool_set", "skill_step"):
        assert supports_release(kind)
    assert supports_release("combination", [{"candidate_type":"prompt"},{"candidate_type":"tool_set"}])
    assert not supports_release("combination", [{"candidate_type":"prompt"},{"candidate_type":"tool_mapping"}])
    assert not supports_release("combination", [])
    assert not supports_release("baseline")
