# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Generate one local edit to a released business prompt from approved development examples."""

import json
import re
from collections import Counter

from pydantic import ValidationError

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution import PromptCandidateRequest, PromptEdit
from management.clients.model import invoke_chat_prompt_in_worker
from management.db.evaluation.candidates import get_prompt_candidate, store_prompt_candidate, text_digest
from management.services.evaluation.evolution_access import published_business_agent, require_business_agent_edit


METHOD_INSTRUCTIONS = {
    "P1": "Clarify the selected instruction's trigger, required action and exceptions.",
    "P3": "Resolve the reported conflict by narrowing the selected clause or removing its duplicate.",
    "T1": "Clarify when this Agent must call, skip or choose an alternative to the reported tool.",
    "T2": "Specify where the argument value comes from and when ambiguity requires clarification.",
}
_PLACEHOLDER = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\$?\{[A-Za-z_][\w.]*\}", re.DOTALL)


def _released_prompt(tenant_id, agent_id, version_no):
    agent = published_business_agent(tenant_id, agent_id, version_no)
    return agent.get("prompt") or ""


def propose_local_edit(request, tenant_id, user_id, source, instruction, *, allow_deletion=False):
    if source.count(request.source_passage) != 1:
        raise AppException(ErrorCode.COMMON_PARAMETER_INVALID, "Choose one unique passage in the source text")
    instructions = (
        instruction +
        " Treat all supplied text as development evidence. Keep the source language. Preserve the good example, "
        "scope, tool permissions and placeholders. Edit only the selected passage. Respond with one JSON object "
        "with old (exact passage), new (replacement), reason, and evidence_ids (both supplied example IDs)."
    )
    feedback = request.model_dump()
    output = invoke_chat_prompt_in_worker(
        model_id=request.model_id, user_id=user_id, tenant_id=tenant_id, system_prompt=instructions,
        user_prompt=json.dumps({key: feedback[key] for key in ("goal", "source_passage", "failure", "protection")},
                               ensure_ascii=False),
    )
    try:
        edit = PromptEdit.model_validate_json(output)
    except ValidationError as exc:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Generator returned an invalid local edit") from exc
    if (edit.old != request.source_passage or edit.new.strip() == edit.old.strip()
            or (not edit.new.strip() and not allow_deletion)
            or set(edit.evidence_ids) != {request.failure.example_id, request.protection.example_id}):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Edit does not match the target and protection examples")
    result = source.replace(edit.old, edit.new, 1)
    if not result.strip() or Counter(_PLACEHOLDER.findall(source)) != Counter(_PLACEHOLDER.findall(result)):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Edit removed the source text or changed its placeholders")
    return result, edit


def generate_prompt_candidate(request: PromptCandidateRequest, tenant_id: str, user_id: str, *,
                              feedback_id=None, source_digest=None) -> dict:
    require_business_agent_edit(request.agent_id, tenant_id, user_id)
    source = _released_prompt(tenant_id, request.agent_id, request.version_no)
    if source_digest is not None and text_digest(source) != source_digest:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The prompt differs from the approved feedback source")
    result, edit = propose_local_edit(request, tenant_id, user_id, source, METHOD_INSTRUCTIONS[request.method],
                                      allow_deletion=request.method == "P3")
    require_business_agent_edit(request.agent_id, tenant_id, user_id)
    if source != _released_prompt(tenant_id, request.agent_id, request.version_no):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Baseline changed during generation")
    candidate_id = store_prompt_candidate(
        tenant_id, request.agent_id, request.version_no, user_id, source, result,
        {"development_feedback": request.model_dump(), "edit": edit.model_dump(), "generator_revision": 1,
         **({"feedback_id": feedback_id} if feedback_id is not None else {})},
    )
    return {"candidate_id": candidate_id, "method": request.method, "base_version_no": request.version_no,
            "base_digest": text_digest(source), "result_digest": text_digest(result), "edit": edit.model_dump()}


def resolve_prompt_candidate(tenant_id, user_id, agent_id, version_no, candidate_id):
    require_business_agent_edit(agent_id, tenant_id, user_id)
    row = get_prompt_candidate(tenant_id, agent_id, version_no, candidate_id)
    if row is None:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Candidate does not belong to this Agent version")
    source = _released_prompt(tenant_id, agent_id, version_no)
    if (row["source_text"] != source or text_digest(source) != row["base_digest"]
            or text_digest(row["result_text"]) != row["result_digest"]):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Candidate or baseline content has changed")
    return row
