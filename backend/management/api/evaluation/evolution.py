# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from typing import Literal
from functools import partial

from fastapi import APIRouter, Header
from contracts.agentos import EvaluationAgentRun

from contracts.evolution import DevelopmentExperimentRequest, PromptCandidateRequest, ReplayCaseRequest, SkillStepCandidateRequest
from contracts.evolution import FeedbackHandoffRequest, GenerateFromFeedbackRequest
from management.db.evaluation.candidates import text_digest
from management.services.agent.preparation.evaluation_snapshot import prepare_evaluation_snapshot
from management.services.evaluation.prompt_candidates import generate_prompt_candidate, resolve_prompt_candidate
from management.services.evaluation.skill_candidates import generate_skill_step_candidate
from management.services.evaluation.replay_cases import freeze_development_case, get_development_case
from management.services.evaluation.experiments import create_experiment, experiment_report, workspace_choices
from management.services.evaluation.feedback_handoff import generate_from_handoff, handoff
from management.services.permission.identity.session import get_current_user_id
from nexent.core.concurrency import run_blocking


router = APIRouter(prefix="/agent-evolution")


@router.get("/agents/{agent_id}/versions/{version_no}/workspace")
async def read_workspace(agent_id: int, version_no: int, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking("read-development-workspace", workspace_choices, tenant_id, user_id, agent_id,
                                version_no, lane="control-io", owner="management")
    return {"data": result}


@router.post("/experiments/{experiment_id}/feedback")
async def share_feedback(experiment_id: int, request: FeedbackHandoffRequest, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    fid = await handoff(tenant_id, user_id, experiment_id, request)
    return {"data": {"feedback_id": fid}}


@router.post("/feedback/{feedback_id}/candidates")
async def create_from_feedback(feedback_id: int, request: GenerateFromFeedbackRequest,
                               authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking("generate-from-development-feedback", generate_from_handoff, tenant_id, user_id,
                                feedback_id, request.model_id, lane="evaluation", owner="management")
    return {"data": result}


@router.post("/experiments", status_code=202)
async def submit_experiment(request: DevelopmentExperimentRequest, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    eid = await create_experiment(request, tenant_id, user_id)
    return {"data": {"experiment_id": eid, "status_url": f"/api/agent-evolution/experiments/{eid}"}}


@router.get("/experiments/{experiment_id}")
async def read_experiment(experiment_id: int, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking("read-experiment", experiment_report, tenant_id, user_id, experiment_id,
                                lane="control-io", owner="management")
    return {"data": result}


@router.post("/experiments/{experiment_id}/cancel")
async def cancel_experiment(experiment_id: int, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking("cancel-experiment", partial(experiment_report, cancel=True),
                                tenant_id, user_id, experiment_id, lane="control-io", owner="management")
    return {"data": result}


@router.post("/development-cases")
async def create_development_case(request: ReplayCaseRequest, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking("freeze-development-case", freeze_development_case, request, user_id, tenant_id,
                                lane="evaluation", owner="management")
    return {"data": result}


@router.get("/agents/{agent_id}/versions/{version_no}/development-cases/{case_id}")
async def read_development_case(agent_id: int, version_no: int, case_id: int, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking("read-development-case", get_development_case, tenant_id, user_id,
                                agent_id, version_no, case_id, lane="control-io", owner="management")
    return {"data": result}


@router.post("/skill-step-candidates")
async def create_skill_step_candidate(request: SkillStepCandidateRequest, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking("generate-skill-step-candidate", generate_skill_step_candidate,
                                request, tenant_id, user_id, lane="evaluation", owner="management")
    return {"data": result}


@router.post("/agents/{agent_id}/versions/{version_no}/skill-candidates/{candidate_id}/preview")
async def preview_skill_candidate(agent_id: int, version_no: int, candidate_id: int, variant: Literal["base", "result"],
                                  authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    snapshot = await prepare_evaluation_snapshot(
        EvaluationAgentRun(agent_id=agent_id, version_no=version_no, query=""), user_id, tenant_id,
        skill_candidate_id=candidate_id, skill_variant=variant,
    )
    ref = next(item for item in snapshot.resource.skill_refs if item.package_candidate_id == candidate_id)
    return {"data": {"candidate_id": candidate_id, "instance_id": ref.instance_id, "variant": variant,
                     "execution_revision": ref.revision}}


@router.post("/prompt-candidates")
async def create_prompt_candidate(request: PromptCandidateRequest, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking(
        "generate-evolution-prompt", generate_prompt_candidate, request, tenant_id, user_id,
        lane="evaluation", owner="management",
    )
    return {"data": result}


@router.post("/agents/{agent_id}/versions/{version_no}/prompt-candidates/{candidate_id}/preview")
async def preview_prompt_candidate(agent_id: int, version_no: int, candidate_id: int,
                                   authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    # Check before loading any baseline resources. Compilation checks again at the source field.
    await run_blocking("authorize-candidate-preview", resolve_prompt_candidate, tenant_id, user_id,
                       agent_id, version_no, candidate_id, lane="control-io", owner="management")
    snapshot = await prepare_evaluation_snapshot(
        EvaluationAgentRun(agent_id=agent_id, version_no=version_no, query=""),
        user_id, tenant_id, prompt_candidate_id=candidate_id,
    )
    options = snapshot.resource.evaluation_options
    inputs = {
        "templates": snapshot.resource.prompt_templates,
        "instructions": options.instructions if options else None,
        "context_items": options.context_items if options else [],
    }
    digest = text_digest(json.dumps(inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return {"data": {"candidate_id": candidate_id, "agent_id": snapshot.resource.agent_id,
                     "version_no": snapshot.resource.version_no, "compiled_prompt_digest": digest}}


@router.get("/agents/{agent_id}/versions/{version_no}/prompt-candidates/{candidate_id}")
async def read_prompt_candidate(agent_id: int, version_no: int, candidate_id: int,
                                authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking(
        "read-evolution-prompt", resolve_prompt_candidate, tenant_id, user_id, agent_id, version_no, candidate_id,
        lane="control-io", owner="management",
    )
    return {"data": result}
