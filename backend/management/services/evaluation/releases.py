# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Materialize a passed candidate from the same inputs used by independent evaluation."""

from sqlalchemy import select

from contracts.releases import supports_release
from contracts.agentos import EvaluationAgentRun
from contracts.errors.exceptions import AppException, SnapshotCompilationError
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.skill_candidate_records import candidate_skill_row, read_bound_skill_candidate
from infrastructure.rdb.skill_execution_records import read_bound_skills, SkillInstance
from infrastructure.skill_execution import capture_skill_files, skill_execution_revision
from infrastructure.skill_package import load_new_skill_package, load_skill_package, released_skill_files, store_skill_package
from management.db.evaluation import releases
from management.services.evaluation.confirmation import verified_recipe
from management.services.evaluation.experiments import snapshot_digest
from management.services.agent.preparation.evaluation_snapshot import prepare_evaluation_snapshot
from management.services.evaluation.prompt_candidates import resolve_prompt_candidate
from nexent.core.concurrency import run_blocking


async def _io(name, fn, *args):
    return await run_blocking(name, fn, *args, lane="control-io", owner="management")


def _confirmed_tool_exclusions(prepared):
    base, result = (prepared[arm].tool_set_check for arm in ("base", "result"))
    if (
        not base
        or not result
        or base.arm != "base"
        or result.arm != "result"
        or not base.removed
        or base.removed != result.removed
        or len(set(base.removed)) != len(base.removed)
    ):
        releases.reject("The two confirmed tool catalogs do not identify the same exclusions")

    def names(arm):
        options = prepared[arm].resource.evaluation_options
        return {item["content"]["name"] for item in options.context_items or () if item["type"] == "tool"}

    before, after = names("base"), names("result")
    if before - after != set(base.removed) or after - before:
        releases.reject("The confirmed tool catalogs differ outside the tested selection")
    return tuple(base.removed)


def _verify_released_guides(tenant, resource):
    for ref in resource.released_skill_guides:
        load_new_skill_package(tenant, resource.agent_id, ref.digest)


def _materials(tenant, ctx, prepared):
    recipe = ctx["recipe"]
    agent, version, kind = ctx["agent_id"], ctx["version_no"], recipe["candidate_type"]
    base, new = (prepared[arm].resource for arm in ("base", "result"))
    if base.subagents or new.subagents or base.external_a2a or new.external_a2a:
        releases.reject("This release requires independently pinned child resources")
    _verify_released_guides(tenant, base)
    prompt = None
    targets = {}
    removed = ()
    scoped_old = {part.candidate_id: part for part in prepared["base"].scoped_skill_trials}
    scoped_new = {part.candidate_id: part for part in prepared["result"].scoped_skill_trials}
    parts = recipe["components"] if kind == "combination" else [recipe]
    if not supports_release(kind, recipe.get("components")):
        releases.reject("This candidate does not have a publishable resource binding")
    for part in parts:
        part_kind, candidate_id = part["candidate_type"], part["candidate_id"]
        if part_kind == "prompt":
            if prompt is not None:
                releases.reject("Two candidates cannot replace the same prompt")
            prompt = resolve_prompt_candidate(
                tenant, ctx["submitted_by"], agent, version, candidate_id
            )["result_text"]
        elif part_kind == "tool_build":
            from management.services.evaluation.tool_build_candidate import build_difference
            if build_difference(base, new) != ctx["plan"].get("tool_build"):
                releases.reject("The independently tested MCP build changed")
        elif part_kind == "tool_mapping" and kind == "tool_mapping":
            from management.services.evaluation.tool_mapping_candidates import mapping_difference
            if mapping_difference(base, new) != ctx["plan"].get("tool_mapping"):
                releases.reject("The independently tested mapping changed")
        elif part_kind == "tool_set":
            if removed:
                releases.reject("Two candidates cannot replace the same tool catalog")
            removed = _confirmed_tool_exclusions(prepared)
        elif part_kind == "skill_new" and kind == "skill_new":
            old_ref, new_ref = (prepared[arm].new_skill_trial for arm in ("base", "result"))
            if (not old_ref or not new_ref or old_ref.arm != "base" or new_ref.arm != "result"
                    or new_ref.candidate_id != candidate_id or old_ref.model_copy(update={"arm": "result"}) != new_ref):
                releases.reject("Independent results do not identify a single new Skill package")
            load_new_skill_package(tenant, agent, new_ref.digest)
        elif part_kind in {"skill_step", "skill_discovery", "skill_script"}:
            scoped = scoped_new.get(candidate_id) if part_kind == "skill_step" else None
            if scoped:
                old = scoped_old.get(candidate_id)
                if not old or old.arm != "base" or scoped.arm != "result" or old.model_copy(update={"arm": "result"}) != scoped:
                    releases.reject("The tested scoped Skill revisions differ from the confirmed binding")
                load_new_skill_package(tenant, agent, scoped.result_digest)
                continue
            target = read_bound_skill_candidate(tenant, agent, version, candidate_id)
            if not target or target["method"] != {"skill_step": "S2", "skill_discovery": "S1", "skill_script": "S4"}[part_kind]:
                releases.reject("The independently tested Skill candidate is unavailable")
            if part_kind == "skill_script" and target["script_build"] != ctx["plan"].get("script_build"):
                releases.reject("The confirmed script build differs from the reviewed candidate")
            instance = target["instance_id"]
            if instance in targets or any(
                not any(ref.instance_id == instance and ref.package_candidate_id == candidate_id
                        and ref.package_variant == arm for ref in prepared[arm].resource.skill_refs)
                for arm in ("base", "result")
            ):
                releases.reject("The tested Skill revisions require distinct, confirmed bindings")
            targets[instance] = target
        else:
            releases.reject("This candidate does not yet have a live resource binding")
    with get_db_session() as session:
        skills = dict(
            session.execute(
                select(SkillInstance.skill_instance_id, SkillInstance.skill_id).where(
                    SkillInstance.tenant_id == tenant,
                    SkillInstance.agent_id == agent,
                    SkillInstance.version_no == version,
                    SkillInstance.enabled.is_(True),
                    SkillInstance.delete_flag == "N",
                )
            ).all()
        )
    rows = read_bound_skills(agent, version, tenant)
    expected = {
        arm: {r.instance_id: r.revision for r in prepared[arm].resource.skill_refs} for arm in prepared
    }
    if any(set(refs) != set(skills) for refs in expected.values()) or {r["instance_id"] for r in rows} != set(
        skills
    ):
        releases.reject("The evaluated Skill set no longer matches the published agent")
    pins = []
    for row in rows:
        instance = row["instance_id"]
        skill = skills[instance]
        result_row = row
        target = targets.get(instance)
        if target:
            try:
                result_row = candidate_skill_row(row, target, "result")
            except ValueError as exc:
                releases.reject(str(exc))
            packages = {
                arm: (target[arm + "_digest"], load_skill_package(tenant, skill, target[arm + "_digest"]))
                for arm in ("base", "result")
            }
        else:
            files = (
                released_skill_files(tenant, agent, version, row)
                if "release_package" in row
                else capture_skill_files(tenant, row["name"])
            )
            digest = store_skill_package(tenant, skill, files)
            packages = {"base": (digest, files), "result": (digest, files)}
        if any(
            skill_execution_revision(tenant, agent, version, result_row if arm == "result" else row, files) != expected[arm][instance]
            for arm, (_, files) in packages.items()
        ):
            releases.reject("Skill files or configuration changed after independent evaluation")
        pin = {"row": row, "skill_id": skill, **packages}
        if result_row.get("script_image"):
            pin["result_image"] = result_row["script_image"]
        if result_row["description"] != row["description"]:
            pin["result_description"] = result_row["description"]
        pins.append(pin)
    baseline = prepared["base"].model_copy(deep=True)
    baseline.resource.skill_refs = [
        r.model_copy(update={"package_candidate_id": None, "package_variant": None})
        for r in baseline.resource.skill_refs
    ]
    if kind == "skill_new":
        baseline.new_skill_trial = None
    baseline.scoped_skill_trials = []
    if any(part["candidate_type"] in {"skill_new", "skill_discovery"} for part in parts):
        baseline.observe_root_skill_choices = None
    baseline.tool_set_check = None
    return pins, prompt, snapshot_digest(baseline), removed


async def promote(tenant, actor, lock, request):
    ctx, existing, stamp = await _io("authorize-evolution-release", releases.prepare, tenant, actor, lock)
    if ctx["version_no"] != request.expected_version or ctx["digest"] != request.candidate_digest:
        releases.reject("The requested version or candidate digest differs from independent confirmation")
    if existing:
        return existing
    prepared = {}
    recipe = await verified_recipe(
        tenant, ctx["submitted_by"], ctx["experiment_id"], ctx["plan"], prepared=prepared
    )
    if recipe != ctx["recipe"]:
        releases.reject("The tested candidate can no longer be reproduced")
    pins, prompt, baseline, removed = await _io("verify-release-packages", _materials, tenant, ctx, prepared)
    guide = (prepared["result"].new_skill_trial.model_dump(exclude={"arm"}) if recipe["candidate_type"] == "skill_new"
             else [trial.model_dump() for trial in prepared["result"].scoped_skill_trials] or None)
    return await _io(
        "publish-evolution-version",
        releases.publish,
        tenant,
        actor,
        lock,
        request.reason,
        request.expected_version,
        request.candidate_digest,
        stamp,
        pins,
        prompt,
        baseline,
        removed,
        guide,
        ctx["plan"].get("tool_mapping") if recipe["candidate_type"] == "tool_mapping" else None,
        ctx["plan"].get("tool_build") if recipe["candidate_type"] == "tool_build" else None,
    )


async def rollback(tenant, actor, lock, request):
    record = await _io("authorize-release-rollback", releases.rollback_target, tenant, actor, lock)
    if record["new_version"] != request.expected_version:
        releases.reject("The requested release differs from the selected version")
    ready = False
    if not record["rollback_at"]:
        try:
            spec = await prepare_evaluation_snapshot(
                EvaluationAgentRun(agent_id=record["agent_id"], version_no=record["base_version"], query=""),
                actor,
                tenant,
                language=record["language"],
            )
            ready = spec is not None and snapshot_digest(spec) == record["baseline_digest"]
            if ready:
                await _io("verify-rollback-guides", _verify_released_guides, tenant, spec.resource)
        except (ValueError, OSError, AppException, SnapshotCompilationError):
            ready = False
    return await _io("rollback-evolution-version", releases.restore, tenant, actor, lock, request, ready)
