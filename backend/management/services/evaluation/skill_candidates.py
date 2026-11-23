# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Propose and evaluate a local change to the execution steps of an existing Skill."""

import re
from hashlib import sha256

from contracts.constants.constants import PERMISSION_EDIT
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution import SkillStepCandidateRequest
from infrastructure.rdb.skill_candidate_records import read_bound_skill_candidate
from infrastructure.rdb.skill_execution_records import read_bound_skills
from infrastructure.skill_execution import capture_skill_files, skill_execution_revision
from infrastructure.skill_package import encode_skill_package, load_skill_package, store_skill_package
from management.db.evaluation.candidates import store_skill_candidate
from management.db.identity.group import query_group_ids_by_user_in_tenant
from management.db.identity.user_tenant import get_user_role_by_tenant
from management.db.skill.repository import get_skill_by_id
from management.services.evaluation.prompt_candidates import propose_local_edit
from management.services.skill.permission import resolve_skill_permission


def _editable_skill(tenant_id, user_id, skill_id):
    roles = get_user_role_by_tenant(user_id, tenant_id)
    skill = get_skill_by_id(skill_id, tenant_id) if roles else None
    if not skill or resolve_skill_permission(skill=skill, user_id=user_id, user_role=roles,
                                             user_group_ids=set(query_group_ids_by_user_in_tenant(user_id, tenant_id) or [])) != PERMISSION_EDIT:
        raise AppException(ErrorCode.COMMON_FORBIDDEN)
    return skill


def generate_skill_step_candidate(request: SkillStepCandidateRequest, tenant_id: str, user_id: str, *,
                                 feedback_id=None, source_digest=None):
    skill = _editable_skill(tenant_id, user_id, request.skill_id)
    files = capture_skill_files(tenant_id, skill["name"])
    if source_digest is not None and sha256(encode_skill_package(files)).hexdigest() != source_digest:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The Skill differs from the approved feedback source")
    guide = files["SKILL.md"].decode("utf-8")
    header = re.match(r"\A---[ \t]*\r?\n.*?^---[ \t]*(?:\r?\n|\Z)", guide, re.MULTILINE | re.DOTALL)
    if not header:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Cannot delimit the Skill guide's metadata")
    result, edit = propose_local_edit(
        request, tenant_id, user_id, guide[header.end():],
        "The correct Skill was already loaded. Compare what the same step did in the failure and good example. "
        "Fix the prerequisite, order, or exception for that step only. Preserve the good branch and output format. "
        "Do not introduce commands, tool privileges, new files or fixed case-specific names.",
    )
    updated = {**files, "SKILL.md": (guide[:header.end()] + result).encode("utf-8")}
    current = _editable_skill(tenant_id, user_id, request.skill_id)
    if current["name"] != skill["name"] or capture_skill_files(tenant_id, current["name"]) != files:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The source Skill changed during generation")
    base = store_skill_package(tenant_id, request.skill_id, files)
    candidate = store_skill_package(tenant_id, request.skill_id, updated)
    _editable_skill(tenant_id, user_id, request.skill_id)
    candidate_id = store_skill_candidate(tenant_id, skill, user_id, base, candidate,
        {"method": "S2", "generator_revision": 1, "development_feedback": request.model_dump(), "edit": edit.model_dump(),
         **({"feedback_id": feedback_id} if feedback_id is not None else {})})
    return {"candidate_id": candidate_id, "method": "S2", "skill_id": request.skill_id,
            "base_digest": base, "result_digest": candidate, "edit": edit.model_dump()}


def pin_skill_candidate(resource, tenant_id, candidate_id, variant):
    if variant not in {"base", "result"}:
        raise ValueError("Unknown Skill package variant")
    bound = read_bound_skill_candidate(tenant_id, resource.agent_id, resource.version_no, candidate_id)
    if not bound:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Skill candidate is outside the Agent binding")
    row = next((item for item in read_bound_skills(resource.agent_id, resource.version_no, tenant_id)
                if item["instance_id"] == bound["instance_id"]), None)
    ref = next((item for item in resource.skill_refs if item.instance_id == bound["instance_id"]), None)
    if not row or not ref:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Skill binding changed during preparation")
    base = load_skill_package(tenant_id, bound["skill_id"], bound["base_digest"])
    scope = (tenant_id, resource.agent_id, resource.version_no, row)
    if skill_execution_revision(*scope, base) != ref.revision:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Released Skill differs from the candidate baseline")
    files = base if variant == "base" else load_skill_package(tenant_id, bound["skill_id"], bound["result_digest"])
    update = dict(package_candidate_id=candidate_id, package_variant=variant, revision=skill_execution_revision(*scope, files))
    resource.skill_refs = [item.model_copy(update=update) if item.instance_id == ref.instance_id else item
                           for item in resource.skill_refs]
