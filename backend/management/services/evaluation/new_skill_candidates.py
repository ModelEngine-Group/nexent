# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Generate an isolated candidate package using the existing signed NL2Skill run."""

import asyncio
import json
from fastapi.concurrency import contextmanager_in_threadpool
from contextlib import aclosing
from pathlib import PurePosixPath

from contracts.agent import NL2SkillRunRequest
from contracts.constants import environment
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution_sources import normalized_text, task_digest
from infrastructure.skill_package import encode_skill_package, load_new_skill_package, store_new_skill_package
from management.db.evaluation import experiments as jobs, generation_attempts, new_skills
from management.db.evaluation.confirmation_runs import exclusive_job_slot
from management.db.skill.repository import get_skill_by_name
from management.services.evaluation.evolution_access import require_business_agent_edit
from management.services.evaluation.experiments import _io
from management.services.evaluation.feedback_handoff import require_development_sources
from management.services.evaluation.generation_budget import finish_generation, source_digest as generation_source
from management.services.evaluation.new_skill_evidence import check_private, invalid, require_creator
from management.services.skill.creation import create_nl2skill_stream, prepare_nl2skill_snapshot
from nexent.skills.skill_loader import SkillLoader


def _authorized_feedback(tenant, user, fid):
    feedback = jobs.read_handoff(tenant, fid)
    if not feedback or feedback.get("method") != "S3" or feedback.get("creator_id") != user:
        raise AppException(ErrorCode.COMMON_FORBIDDEN)
    require_creator(tenant, user)
    plan = jobs.read_plan(tenant, feedback["experiment_id"], True)
    if not plan or task_digest(plan) != feedback["plan_digest"]:
        invalid("The development source is no longer active")
    require_development_sources(tenant, feedback["agent_id"], feedback["source_case_ids"], plan)
    if get_skill_by_name(feedback["brief"]["name"], tenant):
        invalid("The proposed Skill name is already in use")
    return feedback


async def collect_files(stream):
    files, checkpoints = {}, {}
    total = 0
    done = False
    async with aclosing(stream):
        async for frame in stream:
            event = json.loads(frame.removeprefix("data: ").strip())
            kind = event.get("type")
            if kind == "model_attempt_control":
                attempt = event["attempt_id"]
                if event["phase"] == "begin":
                    checkpoints[attempt] = files.copy()
                elif event["phase"] == "rollback" and attempt in checkpoints:
                    files = checkpoints.pop(attempt)
                elif event["phase"] == "commit":
                    checkpoints.pop(attempt, None)
            elif kind in {"skill_body", "file_content"}:
                path = "SKILL.md" if kind == "skill_body" else event.get("path", "")
                value = event["content"]
                location = PurePosixPath(path)
                if kind == "file_content" and (
                    not path.startswith("references/")
                    or location.suffix.lower() not in {".txt", ".md"}
                    or any(p in {".", "..", ""} for p in path.split("/"))
                    or "\\" in path
                ):
                    invalid("New Skill references must be relative text documents")
                total += len(value.encode())
                if total > 131072 or len(files) >= 16 and path not in files:
                    invalid("Generated Skill exceeds the proposal size limit")
                files[path] = files.get(path, "") + value
            elif kind == "done":
                done = True
            elif kind == "error" or kind == "agentos_execution_error":
                invalid("The NL2Skill run failed")
    if not done or checkpoints or not files.get("SKILL.md"):
        invalid("NL2Skill did not finish a complete candidate")
    return files


def _validate_package(files, feedback):
    for name, value in files.items():
        check_private(name, feedback["private_marks"])
        check_private(value, feedback["private_marks"])
    try:
        parsed = SkillLoader.parse(files["SKILL.md"])
    except (TypeError, ValueError) as exc:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Invalid new Skill guide") from exc
    if (
        parsed["name"] != feedback["brief"]["name"]
        or not isinstance(parsed["description"], str)
        or not 0 < len(parsed["description"].strip()) <= 1000
        or not parsed["content"]
        or parsed["allowed_tools"]
        or parsed["script_outputs"]
    ):
        invalid("Guide metadata must match the proposed Skill without adding tool grants")
    body = normalized_text(parsed["content"])
    brief = feedback["brief"]
    offset = 0
    for step in brief["steps"]:
        label = normalized_text(step.split(":", 1)[1])
        position = body.find(label, offset)
        if position < 0:
            invalid("The guide must include each approved step in order")
        offset = position + len(label)
    if any(normalized_text(label) not in body for label in [brief["skip_when"], *brief["parameters"]]):
        invalid("The guide must retain the approved parameters and exclusion condition")
    encoded = {k: v.encode() for k, v in files.items()}
    encode_skill_package(encoded)
    return parsed["description"], encoded


async def generate_new_skill(tenant, user, fid, model_id):
    feedback = await _io("authorize-new-skill-generation", _authorized_feedback, tenant, user, fid)
    prompt = (
        "Create the new Skill described by this approved brief. Use its exact name, write for the "
        "business language of the brief, and include prerequisites, ordered steps, variable inputs, "
        "when to skip the Skill, and the expected deliverable. Steps prefixed tool are observed tools; "
        "outcome steps describe deliverables. In SKILL.md keep the step labels verbatim (without their prefixes) in the given order, plus all parameter names and the exact skip_when condition. Never invent customer data. "
        "Follow the NL2Skill block format: each control tag on its own line. Produce SKILL.md and only necessary text files under references/. Do not declare tool grants.\n"
        + json.dumps(feedback["brief"], ensure_ascii=False)
    )
    plan = await _io("read-skill-brief-language", jobs.read_plan, tenant, feedback["experiment_id"], True)
    if not plan:
        invalid("Development experiment was cancelled")
    payload = await _io(
        "prepare-new-skill-creator",
        prepare_nl2skill_snapshot,
        NL2SkillRunRequest(query=prompt, model_id=model_id, persist_history=False),
        user,
        tenant,
        plan["request"]["language"],
    )
    key = "nexent.new-skill/" + task_digest([tenant, user, fid, model_id, payload.model.revision])
    async with contextmanager_in_threadpool(exclusive_job_slot(key, "This Skill is already being generated")):
        existing = await _io(
            "find-new-skill-candidate",
            new_skills.matching_candidate,
            tenant,
            user,
            fid,
            model_id,
            payload.model.revision,
        )
        if existing is None:
            attempt = await _io("reserve-new-skill-generation", generation_attempts.reserve,
                                tenant, user, generation_source("S3", fid), model_id)
            try:
                async with asyncio.timeout(environment.EVOLUTION_GENERATION_TIMEOUT_SECONDS):
                    files = await collect_files(create_nl2skill_stream(payload, user, tenant))
            except TimeoutError as exc:
                raise AppException(ErrorCode.SYSTEM_TIMEOUT, "Candidate generation exceeded its time budget") from exc
            await _io("complete-new-skill-generation", finish_generation, tenant, attempt)

            def store():
                approved = _authorized_feedback(tenant, user, fid)
                description, encoded = _validate_package(files, approved)
                digest = store_new_skill_package(tenant, approved["agent_id"], encoded)
                return new_skills.save_candidate(
                    tenant, user, fid, approved, description, digest, payload.model
                )

            existing = await _io("store-new-skill-candidate", store)
    return await _io("read-new-skill-preview", preview_new_skill, tenant, user, existing)


def preview_new_skill(tenant, user, cid):
    row = new_skills.find_candidate(tenant, cid)
    if not row:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    if user == row["created_by"]:
        try:
            require_creator(tenant, user)
        except AppException as exc:
            if exc.error_code != ErrorCode.COMMON_FORBIDDEN:
                raise
            require_business_agent_edit(row["agent_id"], tenant, user)
    else:
        require_business_agent_edit(row["agent_id"], tenant, user)
    files = load_new_skill_package(tenant, row["agent_id"], row["digest"])
    return {**row, "method": "S3", "files": {path: value.decode() for path, value in files.items()}}
