# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Apply independent Agent and Skill permissions to chat receipt actions."""

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.db.evaluation.suggestion_actions import receipt_target
from management.services.evaluation.evolution_access import require_business_agent_edit
from management.services.evaluation.skill_candidates import authorize_step_revision, revise_skill_step_candidate


def _allowed(check, *args):
    try:
        check(*args)
    except AppException as exc:
        if exc.error_code not in {ErrorCode.COMMON_FORBIDDEN, ErrorCode.COMMON_RESOURCE_NOT_FOUND,
                                  ErrorCode.AGENTSPACE_AGENT_NOT_FOUND}:
            raise
        return False
    return True


def _editable_candidate(target):
    edit = (target.get("feedback") or {}).get("edit") or {}
    return target["candidate_id"] is not None and bool(edit.get("old") and edit.get("new"))


def suggestion_actions(tenant, user, conversation, message):
    target = receipt_target(tenant, user, conversation, message)
    if target is None:
        return {}
    actions = {}
    if _allowed(require_business_agent_edit, target["agent_id"], tenant, user):
        actions["compare"] = {key: target[key] for key in ("agent_id", "version_no", "experiment_id", "suggestion_id", "candidate_id")}
    if _editable_candidate(target) and _allowed(authorize_step_revision, tenant, user, target):
        actions["edit"] = {"candidate_id": target["candidate_id"]}
    return actions


def suggestion_candidate(tenant, user, conversation, message, candidate, replacement=None):
    target = receipt_target(tenant, user, conversation, message, candidate)
    if target is None or not _editable_candidate(target):
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    if replacement is not None:
        return revise_skill_step_candidate(tenant, user, target, replacement)
    authorize_step_revision(tenant, user, target)
    edit = target["feedback"]["edit"]
    return {"skill_name": target["skill_name"], "old": edit["old"], "new": edit["new"]}
