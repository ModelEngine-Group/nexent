# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from typing import Literal
from functools import partial

from fastapi import APIRouter, Header, Query, Response
from contracts.agentos import EvaluationAgentRun
from contracts.confirmation import ConfirmationLockRequest, ConfirmationManifest, CuratorGrant

from contracts.evolution import DevelopmentExperimentRequest, PromptCandidateRequest, ReplayCaseRequest, SkillStepCandidateRequest
from contracts.evolution import DiscoveryHandoffRequest, ExampleCandidateRequest, FeedbackHandoffRequest, GenerateFromFeedbackRequest
from contracts.evolution import PublicBenchmarkRequest
from contracts.skill_script_repair import ReviewedScriptBuild, ScriptDraftRequest, ScriptRepairFeedback
from management.services.evaluation.skill_script_repairs import build_reviewed_script, draft_script, share_script_feedback
from contracts.tool_repair import ReviewedToolBuild, ToolCallerApproval, ToolRepairRequest
from management.services.evaluation.tool_builds import approve_guard, build_status, list_builds, register_build
from management.services.evaluation.tool_repairs import maintainer_brief, share_tool_brief
from contracts.new_skill_candidates import NewSkillBriefRequest
from contracts.releases import PromotionRequest, RollbackRequest
from management.db.evaluation.experiments import read_handoff
from management.services.evaluation.new_skill_candidates import generate_new_skill, preview_new_skill
from management.services.evaluation.new_skill_evidence import share_new_skill_brief
from management.db.evaluation.releases import release_view, set_publisher
from management.db.evaluation.release_monitoring import release_monitoring
from management.services.evaluation.releases import promote, rollback
from management.db.evaluation.candidates import text_digest
from management.db.evaluation.confirmation import register_suite, set_curator
from management.db.evaluation.confirmation_locks import locked_protocol
from management.db.evaluation.confirmation_runs import result_for_experiment
from management.services.evaluation.evolution_access import published_business_agent, require_business_agent_edit
from management.services.evaluation.confirmation import approve_comparison, nominate_candidate
from management.services.agent.preparation.evaluation_snapshot import prepare_evaluation_snapshot
from management.services.evaluation.prompt_candidates import generate_prompt_candidate, resolve_prompt_candidate
from management.services.evaluation.skill_candidates import generate_skill_step_candidate
from management.services.evaluation.replay_cases import freeze_development_case, get_development_case, preview_trace_case
from management.services.evaluation.experiments import create_experiment, experiment_report, workspace_choices
from management.services.evaluation.public_benchmarks import read_reports, record_report
from management.services.evaluation.feedback_handoff import examples_from_experiment, generate_from_handoff, handoff
from management.services.evaluation.feedback_handoff import tool_mapping_from_experiment, tool_sets_from_experiment
from contracts.evolution import RegressionMembershipRequest, ToolMappingProposal, ToolSetProposal
from management.services.evaluation.replay_cases import update_regression_case
from management.services.permission.identity.session import get_current_user_id
from nexent.core.concurrency import run_blocking


router = APIRouter(prefix="/agent-evolution")


@router.get("/experiments/{experiment_id}/public_benchmark_reports")
async def read_public_benchmarks(
    experiment_id: int,
    before: int | None = Query(None, gt=0),
    limit: int = Query(20, ge=1, le=100),
    authorization: str | None = Header(None),
):
    user, tenant = get_current_user_id(authorization)
    data = await run_blocking("read-public-benchmarks", read_reports, tenant, user, experiment_id, before, limit,
                              lane="control-io", owner="management")
    return {"data": data}


@router.post("/experiments/{experiment_id}/public_benchmark_reports")
async def record_public_benchmark(
    experiment_id: int, request: PublicBenchmarkRequest, authorization: str | None = Header(None)
):
    user, tenant = get_current_user_id(authorization)
    data = await run_blocking("record-public-benchmark", record_report, tenant, user, experiment_id, request,
                              lane="control-io", owner="management")
    return {"data": data}


@router.put("/agents/{agent_id}/release-owners")
async def change_release_owner(
    agent_id: int, request: CuratorGrant, authorization: str | None = Header(None)
):
    user, tenant = get_current_user_id(authorization)

    def configure():
        require_business_agent_edit(agent_id, tenant, user)
        set_publisher(tenant, agent_id, user, request)

    await run_blocking("configure-evolution-publisher", configure, lane="control-io", owner="management")
    return {"data": request.model_dump()}


@router.post("/confirmation-locks/{lock_id}/promote")
async def promote_release(lock_id: int, request: PromotionRequest, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {"data": await promote(tenant, user, lock_id, request)}


@router.get("/confirmation-locks/{lock_id}/release/monitoring")
async def read_release_monitoring(lock_id: int, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {"data": await run_blocking("read-release-monitoring", release_monitoring, tenant, user, lock_id,
                                       lane="evaluation", owner="management")}


@router.get("/confirmation-locks/{lock_id}/release")
async def read_release(lock_id: int, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {
        "data": await run_blocking(
            "read-evolution-release",
            release_view,
            tenant,
            user,
            lock_id,
            lane="control-io",
            owner="management",
        )
    }


@router.post("/confirmation-locks/{lock_id}/rollback")
async def rollback_release(lock_id: int, request: RollbackRequest, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {"data": await rollback(tenant, user, lock_id, request)}


@router.get("/experiments/{experiment_id}/confirmation-results")
async def read_independent_results(experiment_id: int, authorization: str | None = Header(None)):
    from management.db.evaluation.experiments import scope
    from contracts.errors.codes import ErrorCode
    from contracts.errors.exceptions import AppException
    user, tenant = get_current_user_id(authorization)
    def read():
        experiment = scope(tenant,experiment_id)
        if not experiment:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        require_business_agent_edit(experiment["agent_id"],tenant,user)
        return result_for_experiment(tenant,experiment_id)
    return {"data":await run_blocking("read-independent-results",read,lane="control-io",owner="management")}


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
async def read_workspace(agent_id: int, version_no: int, response: Response, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await run_blocking("read-development-workspace", workspace_choices, tenant_id, user_id, agent_id,
                                version_no, lane="control-io", owner="management")
    response.headers["Cache-Control"] = "private, no-store"
    return {"data": result}


@router.post("/experiments/{experiment_id}/feedback")
async def share_feedback(experiment_id: int, request: FeedbackHandoffRequest | DiscoveryHandoffRequest,
                         authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    fid = await handoff(tenant_id, user_id, experiment_id, request)
    return {"data": {"feedback_id": fid}}


@router.post("/experiments/{experiment_id}/new-skill-brief")
async def propose_new_skill(experiment_id: int, request: NewSkillBriefRequest, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {"data": await share_new_skill_brief(tenant, user, experiment_id, request)}


@router.get("/new-skill-candidates/{candidate_id}")
async def read_new_skill(candidate_id: int, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    result = await run_blocking(
        "preview-new-skill", preview_new_skill, tenant, user, candidate_id, lane="control-io", owner="management"
    )
    return {"data": result}


@router.post("/feedback/{feedback_id}/candidates")
async def create_from_feedback(feedback_id: int, request: GenerateFromFeedbackRequest,
                               authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    feedback = await run_blocking(
        "identify-feedback-method", read_handoff, tenant_id, feedback_id, lane="control-io", owner="management"
    )
    if feedback and feedback.get("method") == "S3":
        return {"data": await generate_new_skill(tenant_id, user_id, feedback_id, request.model_id)}
    result = await run_blocking("generate-from-development-feedback", generate_from_handoff, tenant_id, user_id,
                                feedback_id, request.model_id, lane="evaluation", owner="management")
    return {"data": result}


@router.post("/experiments/{experiment_id}/example-candidates")
async def select_prompt_examples(experiment_id: int, request: ExampleCandidateRequest,
                                 authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    result = await examples_from_experiment(tenant_id, user_id, experiment_id, request)
    return {"data": result}


@router.post("/experiments/{experiment_id}/tool-repair-feedback")
async def freeze_tool_repair(experiment_id: int, request: ToolRepairRequest, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {"data": {"feedback_id": await share_tool_brief(tenant, user, experiment_id, request)}}


@router.get("/feedback/{feedback_id}/tool-repair-brief")
async def read_tool_repair_brief(feedback_id: int, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    result = await run_blocking("read-tool-maintainer-brief", maintainer_brief, tenant, user, feedback_id,
                                lane="evaluation", owner="management")
    return {"data": result}


@router.post("/feedback/{feedback_id}/tool-builds")
async def register_reviewed_tool(feedback_id: int, request: ReviewedToolBuild, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    result = await run_blocking("register-reviewed-tool", register_build, tenant, user, feedback_id, request,
                                lane="evaluation", owner="management")
    return {"data": result}


@router.get("/feedback/{feedback_id}/tool-builds")
async def registered_tool_builds(feedback_id: int, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {"data": await run_blocking("list-tool-builds", list_builds, tenant, user, feedback_id,
                                       lane="evaluation", owner="management")}


@router.post("/tool-builds/{build_id}/caller-cases")
async def approve_tool_caller_case(build_id: int, request: ToolCallerApproval, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {"data": await approve_guard(tenant,user,build_id,request)}


@router.get("/tool-builds/{build_id}")
async def read_tool_build(build_id: int, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {"data": await run_blocking("read-tool-build",build_status,tenant,user,build_id,
                                       lane="evaluation",owner="management")}


@router.post("/experiments/{experiment_id}/skill-script-feedback")
async def freeze_script_examples(experiment_id: int, request: ScriptRepairFeedback, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    return {"data": {"feedback_id": await share_script_feedback(tenant, user, experiment_id, request)}}


@router.post("/feedback/{feedback_id}/skill-script-draft")
async def preview_script_draft(feedback_id: int, request: ScriptDraftRequest, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    result = await run_blocking("draft-skill-function", draft_script, tenant, user, feedback_id, request,
                                lane="evaluation", owner="management")
    return {"data": result}


@router.post("/feedback/{feedback_id}/skill-script-build")
async def create_reviewed_script_build(feedback_id: int, request: ReviewedScriptBuild, authorization: str | None = Header(None)):
    user, tenant = get_current_user_id(authorization)
    result = await run_blocking("build-reviewed-skill-script", build_reviewed_script, tenant, user, feedback_id, request,
                                lane="evaluation", owner="management")
    return {"data": result}


@router.post("/experiments/{experiment_id}/tool-mapping-candidates")
async def propose_tool_mapping(experiment_id: int, request: ToolMappingProposal, authorization: str | None = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    return {"data": await tool_mapping_from_experiment(tenant_id, user_id, experiment_id, request)}


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
