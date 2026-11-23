# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Derive reusable observable steps without sending the source cases to NL2Skill."""

import json
import re
from difflib import SequenceMatcher
from hashlib import sha256

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution import DevelopmentExperimentRequest
from contracts.evolution_sources import example_source_keys, normalized_text, task_digest
from infrastructure.rdb.skill_execution_records import read_bound_skills
from management.db.evaluation import experiments as jobs
from management.db.identity.user_tenant import get_user_role_by_tenant
from management.db.skill.repository import get_skill_by_name
from management.services.evaluation.evolution_access import require_business_agent_edit
from management.services.evaluation.experiments import _io, _snapshot, snapshot_digest
from management.services.evaluation.feedback_handoff import require_development_sources
from management.services.evaluation.replay_cases import get_development_case
from management.services.evaluation.skill_candidates import feedback_skill_files
from permissions.rbac import has_permission
from nexent.skills.skill_loader import SkillLoader


def invalid(message):
    raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, message)


def require_creator(tenant, user):
    roles = get_user_role_by_tenant(user, tenant)
    if not roles or not has_permission(roles, "skill:create"):
        raise AppException(ErrorCode.COMMON_FORBIDDEN)


def private_mark(value):
    text = normalized_text(value)
    return len(text), sha256(text.encode()).hexdigest()


def check_private(text, marks):
    content = normalized_text(text)
    by_length = {}
    for size, digest in marks:
        by_length.setdefault(size, set()).add(digest)
    for length, protected in by_length.items():
        if any(
            sha256(content[i : i + length].encode()).hexdigest() in protected
            for i in range(len(content) - length + 1)
        ):
            invalid("A private sample value occurs in the proposed Skill")


def identifier_marks(material):
    words = re.findall(
        r"https?://[^\s\x22<>]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<![0-9])[0-9]{6,}(?![0-9])", material
    )
    return {private_mark(word) for word in words}


def observed_steps(record, trial, case):
    result = trial.get("result") or {}
    if (
        trial.get("status") != "pass"
        or not trial.get("receipt_id")
        or result.get("case_digest") != case["digest"]
        or (result.get("judgment") or {}).get("status") != "pass"
    ):
        invalid("Every source needs a matching successful baseline receipt")
    grade = result.get("tool_use") or {}
    if grade and grade.get("status") != "pass":
        invalid("Source tool actions were not verified")
    actions = [
        "tool:" + name
        for name in grade.get("sequence", [])
        if name not in {"read_skill_md", "read_skill_config"}
    ]
    if len(actions) > 80:
        invalid("Select a shorter business procedure")
    answer, expected = result.get("answer") or "", case["task"]["expected"]
    offsets = []
    for outcome in record.outcomes:
        if answer.count(outcome.excerpt) != 1 or outcome.excerpt not in expected:
            invalid("Select a unique observed outcome that also occurs in the expected deliverable")
        start = answer.index(outcome.excerpt)
        offsets.append((start, start + len(outcome.excerpt), "outcome:" + outcome.step))
    offsets.sort()
    if any(current[0] < previous[1] for previous, current in zip(offsets, offsets[1:])):
        invalid("Outcome evidence overlaps")
    return actions + [step for _, _, step in offsets]


def common_steps(sequences):
    # Keep only ordered blocks present in every approved task. Ties follow the input case order.
    shared = sequences[0]
    for sequence in sequences[1:]:
        blocks = SequenceMatcher(None, shared, sequence, autojunk=False).get_matching_blocks()
        shared = [step for block in blocks for step in shared[block.a : block.a + block.size]]
    return shared


def _collect(tenant, editor, eid, request):
    scope = jobs.scope(tenant, eid)
    if not scope:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    agent, version = scope["agent_id"], scope["version_no"]
    require_business_agent_edit(agent, tenant, editor)
    require_creator(tenant, request.creator_id)
    plan = jobs.read_plan(tenant, eid, True)
    if not plan or plan["request"]["candidate_type"] != "baseline":
        invalid("Select an active baseline experiment")
    ids = sorted([r.case_id for r in request.successes] + [request.counterexample_id])
    require_development_sources(tenant, agent, ids, plan)
    rows = jobs.trials(tenant, eid)
    if any(r["status"] in {"pending", "running", "cancelled"} for r in rows):
        invalid("Finish the source experiment before preparing a new Skill")
    trials = {r["case_id"]: r for r in rows if r["variant"] == "base"}
    sources, marks, sequences, receipts = set(), set(), [], []
    examples = {s.case_id: s for s in request.successes}
    for cid in ids:
        case = get_development_case(tenant, editor, agent, version, cid)
        task = case["task"]
        keys = example_source_keys(task)
        if (
            not any(k.startswith(("group:", "file:", "conversation:", "file-state:")) for k in keys)
            or keys & sources
        ):
            invalid("Use independently identified source materials")
        sources.update(keys)
        trial = trials.get(cid) or {}
        if (
            plan["cases"].get(str(cid)) != case["digest"]
            or not trial.get("receipt_id")
            or trial["status"] not in {"pass", "fail"}
            or (trial["result"] or {}).get("snapshot_digest") != plan["snapshots"]["base"]
            or trial["result"].get("case_digest") != case["digest"]
            or trial["result"].get("evaluator_id") != plan["request"]["evaluator_id"]
            or not plan.get("evaluator", {}).get("version_no")
            or trial["result"].get("evaluator_version") != plan["evaluator"]["version_no"]
        ):
            invalid("Case or baseline receipt differs from the frozen experiment")
        receipts.append(trial["receipt_id"])
        material = " ".join([task["query"], task["expected"], trial["result"].get("answer") or ""])
        marks.update(identifier_marks(material))
        if cid not in examples:
            continue
        item = examples[cid]
        sequences.append(observed_steps(item, trial, case))
        for value in item.private_values:
            if value not in material:
                invalid("Private values must refer to the selected business sample")
            marks.add(private_mark(value))
    shared = common_steps(sequences)
    from infrastructure.rdb.released_skill_guides import read_released_guides
    assigned = {s["name"] for s in read_bound_skills(agent, version, tenant)}
    assigned.update(s["name"] for s in read_released_guides(tenant, agent, version))
    if request.name in assigned or get_skill_by_name(request.name, tenant):
        invalid("A Skill with this name already exists")
    covered = set()
    for row in request.covered:
        if row.skill not in assigned:
            invalid("Coverage must reference a Skill of this business Agent")
        guide = feedback_skill_files(tenant, row.skill, (agent, version))["SKILL.md"].decode()
        if row.passage not in guide or row.step not in shared:
            invalid("Coverage must identify an existing instruction and an observed step")
        covered.add(row.step)
    for name in assigned:
        text = feedback_skill_files(tenant, name, (agent, version))["SKILL.md"].decode()
        guide = normalized_text(SkillLoader.parse(text)["content"])
        covered.update(
            step for step in shared if step.startswith("outcome:") and normalized_text(step[8:]) in guide
        )
    steps = [step for step in shared if step not in covered]
    if not steps:
        invalid("No shared uncovered step was demonstrated")
    brief = dict(
        name=request.name,
        purpose=request.purpose,
        skip_when=request.skip_when,
        parameters=request.parameters,
        steps=steps,
    )
    check_private(json.dumps(brief, ensure_ascii=False), marks)
    return plan, dict(
        method="S3",
        agent_id=agent,
        version_no=version,
        experiment_id=eid,
        creator_id=request.creator_id,
        source_case_ids=ids,
        success_case_ids=sorted(examples),
        counterexample_id=request.counterexample_id,
        source_keys=sorted(sources),
        receipts=receipts,
        private_marks=sorted(marks),
        brief=brief,
        covered=sorted(covered),
        baseline_digest=plan["snapshots"]["base"],
        plan_digest=task_digest(plan),
    )


async def share_new_skill_brief(tenant, editor, eid, request):
    plan, feedback = await _io("collect-new-skill-evidence", _collect, tenant, editor, eid, request)
    baseline = await _snapshot(
        DevelopmentExperimentRequest.model_validate(plan["request"]), tenant, editor, "base"
    )
    if snapshot_digest(baseline) != feedback["baseline_digest"]:
        invalid("The source Agent changed after the successful runs")
    await _io("authorize-new-skill-brief", require_business_agent_edit, feedback["agent_id"], tenant, editor)
    fid = await _io("save-new-skill-brief", jobs.store_handoff, tenant, editor, eid, feedback)
    return {"feedback_id": fid, "steps": feedback["brief"]["steps"], "covered": feedback["covered"]}
