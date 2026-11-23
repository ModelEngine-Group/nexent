# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from typing import Literal
from functools import partial

from fastapi import APIRouter, Header, Query, Response
from contracts.agentos import EvaluationAgentRun
from contracts.confirmation import ConfirmationLockRequest, ConfirmationManifest, CuratorGrant

from contracts.evolution import DevelopmentExperimentRequest, PromptCandidateRequest, ReplayCaseRequest, SkillStepCandidateRequest
from contracts.evolution import DiscoveryHandoffRequest, ExampleCandidateRequest, FeedbackHandoffRequest, GenerateFromFeedbackRequest
from management.db.evaluation.candidates import text_digest
from management.db.evaluation.confirmation import register_suite, set_curator
from management.db.evaluation.confirmation_locks import locked_protocol
from management.services.evaluation.evolution_access import published_business_agent, require_business_agent_edit
from management.services.evaluation.confirmation import approve_comparison, nominate_candidate
from management.services.agent.preparation.evaluation_snapshot import prepare_evaluation_snapshot
from management.services.evaluation.prompt_candidates import generate_prompt_candidate, resolve_prompt_candidate
from management.services.evaluation.skill_candidates import generate_skill_step_candidate
from management.services.evaluation.replay_cases import freeze_development_case, get_development_case, preview_trace_case
from management.services.evaluation.experiments import create_experiment, experiment_report, workspace_choices
from management.services.evaluation.feedback_handoff import examples_from_experiment, generate_from_handoff, handoff
from management.services.evaluation.feedback_handoff import tool_sets_from_experiment
from contracts.evolution import RegressionMembershipRequest, ToolSetProposal
from management.services.evaluation.replay_cases import update_regression_case
from management.services.permission.identity.session import get_current_user_id
from nexent.core.concurrency import run_blocking


router = APIRouter(prefix="/agent-evolution")


@router.post("/experiments/{experiment_id}/confirmation-candidate")
async def submit_confirmation_candidate(experiment_id: int, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {"data":await nominate_candidate(tenant, user, experiment_id)}


@router.post("/confirmation-suites/{suite_id}/locks")
async def lock_independent_comparison(suite_id: int, request: ConfirmationLockRequest, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {"data":await approve_comparison(tenant, user, suite_id, request)}


@router.get("/confirmation-locks/{lock_id}")
async def read_confirmation_lock(lock_id: int, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    protocol = await run_blocking("read-confirmation-protocol", locked_protocol, tenant, user, lock_id,
                                  lane="control-io", owner="management")
    return {"data":protocol}


@router.put("/agents/{agent_id}/confirmation-curators")
async def change_confirmation_curator(agent_id: int, request: CuratorGrant, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    def configure():
        require_business_agent_edit(agent_id, tenant, user)
        set_curator(tenant, agent_id, user, request)
    await run_blocking("configure-confirmation-curator", configure, lane="control-io", owner="management")
    return {"data":{"user_id":request.user_id,"enabled":request.enabled}}


@router.post("/confirmation-suites")
async def seal_confirmation_suite(request: ConfirmationManifest, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    def seal():
        published_business_agent(tenant, request.agent_id, request.version_no)
        return register_suite(tenant, user, request)
    receipt = await run_blocking("register-confirmation-suite", seal, lane="control-io", owner="management")
    return {"data":receipt}


@router.get("/agents/{agent_id}/versions/{version_no}/workspace")
async def read_workspace(agent_id: int, version_no: int, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking("read-development-workspace", workspace_choices, tenant_id, user_id, agent_id,
                                version_no, lane="control-io", owner="management")
    return {"data": result}


@router.post("/experiments/{experiment_id}/feedback")
async def share_feedback(experiment_id: int, request: FeedbackHandoffRequest | DiscoveryHandoffRequest,
                         authorization: str | None = Header(None)):
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


@router.post("/experiments/{experiment_id}/example-candidates")
async def select_prompt_examples(experiment_id: int, request: ExampleCandidateRequest,
                                 authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await examples_from_experiment(tenant_id, user_id, experiment_id, request)
    return {"data": result}


@router.post("/experiments/{experiment_id}/tool-set-candidates")
async def propose_tool_sets(experiment_id: int, request: ToolSetProposal, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    return {"data": await tool_sets_from_experiment(tenant_id, user_id, experiment_id, request)}


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


@router.get("/agents/{agent_id}/versions/{version_no}/reviews/{turn_id}/case-draft")
async def review_case_draft(agent_id: int, version_no: int, turn_id: int, response: Response,
                            use_previous_task: bool = False, authorization: str | None = Header(None),
                            preceding_turns: int = Query(0, ge=0, le=15)):
    user_id, tenant_id = get_current_user_id(authorization)
    draft = await run_blocking("preview-trace-case", preview_trace_case, tenant_id, user_id, agent_id,
                               version_no, turn_id, use_previous_task, preceding_turns, lane="control-io", owner="management")
    response.headers["Cache-Control"] = "private, no-store"
    return {"data": draft}


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


@router.post("/agents/{agent_id}/versions/{version_no}/development-cases/{case_id}/regression")
async def set_fixed_regression_case(agent_id: int, version_no: int, case_id: int, request: RegressionMembershipRequest,
                                    authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking("update-fixed-regression-case", update_regression_case, tenant_id, user_id,
                                agent_id, version_no, case_id, request.enabled, request.evaluator_id, request.judge_model_id,
                                request.language, lane="control-io", owner="management")
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
