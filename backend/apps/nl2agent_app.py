"""HTTP API for the NL2AGENT conversational agent generator.

This router exposes session-management endpoints (start, apply-local-resources,
install-web-skill, finalize). The conversational chat itself runs through the
existing ``POST /agent/run`` endpoint with the NL2AGENT default agent_id, so no
new chat endpoint is needed here.
"""

import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from consts.error_code import ErrorCode
from consts.exceptions import (
    AppException,
    AgentRunException,
    Nl2AgentExternalServiceError,
    Nl2AgentOperationError,
    Nl2AgentValidationError,
    UnauthorizedError,
)
from consts.model import (
    Nl2AgentApplyLocalResourcesRequest,
    Nl2AgentCardDeliveryRequest,
    Nl2AgentFinalizeRequest,
    Nl2AgentInstallWebSkillRequest,
    Nl2AgentIdentityRequest,
    Nl2AgentMcpBindToolsRequest,
    Nl2AgentMcpInstallRequest,
    Nl2AgentModelSelectionRequest,
    Nl2AgentOnlineRecommendationBatchRequest,
    Nl2AgentRecommendationBatchRequest,
    Nl2AgentRecommendationSkipRequest,
    Nl2AgentRequirementsConfirmRequest,
    Nl2AgentRequirementsSummaryRequest,
)
from consts.nl2agent_response import (
    Nl2AgentApplyLocalResourcesResponse,
    Nl2AgentCardDeliveryResponse,
    Nl2AgentFinalizeResponse,
    Nl2AgentIdentityResponse,
    Nl2AgentLocalRecommendationResponse,
    Nl2AgentLocalSkipResponse,
    Nl2AgentMcpBindToolsResponse,
    Nl2AgentMcpInstallResponse,
    Nl2AgentMcpSkipToolsResponse,
    Nl2AgentModelSelectionResponse,
    Nl2AgentOnlineConfigurationResponse,
    Nl2AgentOnlineRecommendationResponse,
    Nl2AgentRequirementsConfirmationResponse,
    Nl2AgentRequirementsRegistrationResponse,
    Nl2AgentSessionStartResponse,
    Nl2AgentSessionListResponse,
    Nl2AgentSessionSummaryResponse,
    Nl2AgentSessionStateResponse,
    Nl2AgentWebSkillInstallResponse,
    Nl2AgentWebSkillConfigurationResponse,
)
from services.nl2agent_service import (
    apply_local_resources_batch,
    confirm_online_resource_configuration,
    confirm_requirements_review,
    finalize_agent,
    install_web_skill,
    bind_mcp_tools,
    install_recommended_mcp,
    get_session_state,
    get_web_skill_configuration,
    register_local_resource_recommendations,
    register_online_resource_recommendations,
    register_requirements_review,
    report_card_delivery,
    resume_session,
    save_agent_identity,
    select_models,
    skip_mcp_tool_binding,
    skip_local_resource_recommendations,
    start_session,
)
from services.nl2agent_session_lifecycle_service import (
    abandon_session,
    cleanup_expired_sessions,
    list_active_sessions,
    resolve_session,
)
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/nl2agent")
logger = logging.getLogger("nl2agent_app")


def _current_user(
    authorization: Optional[str], http_request: Request
) -> tuple[str, str, str]:
    """Authenticate one NL2AGENT request at the HTTP boundary."""
    try:
        return get_current_user_info(authorization, http_request)
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def _session_http_error(exc: Exception) -> Exception:
    """Convert legacy service failures without inspecting message text."""
    if isinstance(exc, AppException):
        return exc
    if isinstance(exc, Nl2AgentValidationError):
        return AppException(
            ErrorCode.AGENTSPACE_NL2AGENT_INVALID_REQUEST,
            str(exc),
        )
    if isinstance(exc, Nl2AgentExternalServiceError):
        return AppException(
            ErrorCode.AGENTSPACE_NL2AGENT_EXTERNAL_SERVICE_FAILED,
            str(exc),
        )
    if isinstance(exc, Nl2AgentOperationError):
        return AppException(
            ErrorCode.AGENTSPACE_NL2AGENT_OPERATION_FAILED,
            str(exc),
        )
    if isinstance(exc, AgentRunException):
        return AppException(
            ErrorCode.AGENTSPACE_NL2AGENT_WORKFLOW_CONFLICT,
            str(exc),
        )
    logger.exception("NL2AGENT session operation failed")
    return AppException(
        ErrorCode.SYSTEM_INTERNAL_ERROR,
        "Failed to load or update NL2AGENT session state.",
    )


@router.get(
    "/sessions",
    response_model=Nl2AgentSessionListResponse,
    response_model_exclude_none=True,
)
async def list_sessions_api(
    http_request: Request,
    limit: int = 50,
    authorization: Optional[str] = Header(None),
):
    """List the current user's active NL2AGENT sessions."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return {
            "sessions": list_active_sessions(
                tenant_id=tenant_id,
                user_id=user_id,
                limit=limit,
            )
        }
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.get(
    "/session/by-conversation/{conversation_id}",
    response_model=Nl2AgentSessionSummaryResponse,
    response_model_exclude_none=True,
)
async def resolve_session_api(
    conversation_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Resolve an owned active or completed session after browser state is lost."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return resolve_session(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/resume",
    response_model=Nl2AgentSessionSummaryResponse,
    response_model_exclude_none=True,
)
async def resume_session_api(
    agent_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Resume one completed NL2AGENT session without resetting its workflow."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return resume_session(agent_id, tenant_id, user_id)
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/abandon",
    response_model=Nl2AgentSessionSummaryResponse,
    response_model_exclude_none=True,
)
async def abandon_session_api(
    agent_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Explicitly end one owned draft session without deleting it immediately."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return abandon_session(
            draft_agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.put(
    "/session/{agent_id}/models",
    response_model=Nl2AgentModelSelectionResponse,
    response_model_exclude_none=True,
)
async def select_models_api(
    agent_id: int,
    payload: Nl2AgentModelSelectionRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await select_models(
            agent_id=agent_id,
            primary_model_id=payload.primary_model_id,
            fallback_model_ids=payload.fallback_model_ids,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/mcp/install",
    response_model=Nl2AgentMcpInstallResponse,
    response_model_exclude_none=True,
)
async def install_recommended_mcp_api(
    agent_id: int,
    payload: Nl2AgentMcpInstallRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await install_recommended_mcp(
            agent_id=agent_id,
            recommendation_id=payload.recommendation_id,
            option_id=payload.option_id,
            config_values=payload.config_values,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/mcp/{mcp_id}/bind-tools",
    response_model=Nl2AgentMcpBindToolsResponse,
)
async def bind_mcp_tools_api(
    agent_id: int,
    mcp_id: int,
    payload: Nl2AgentMcpBindToolsRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await bind_mcp_tools(
            agent_id=agent_id,
            mcp_id=mcp_id,
            tool_ids=payload.tool_ids,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/mcp/{mcp_id}/skip-tools",
    response_model=Nl2AgentMcpSkipToolsResponse,
)
async def skip_mcp_tools_api(
    agent_id: int,
    mcp_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await skip_mcp_tool_binding(agent_id, mcp_id, tenant_id, user_id)
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post("/session/start", response_model=Nl2AgentSessionStartResponse)
async def start_session_api(
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Start a new NL2AGENT session: creates a draft agent and a conversation.

    Returns ``{"agent_id": int, "conversation_id": int, "draft_name": str}``.
    The frontend then opens the chat page with the NL2AGENT default agent_id
    and this conversation_id.
    """
    user_id, tenant_id, language = _current_user(authorization, http_request)

    try:
        try:
            cleanup_expired_sessions()
        except Exception:
            logger.warning(
                "Failed to clean expired NL2AGENT sessions before start",
                exc_info=True,
            )
        return await start_session(
            user_id=user_id,
            tenant_id=tenant_id,
            language=language,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/apply-local-resources",
    response_model=Nl2AgentApplyLocalResourcesResponse,
)
async def apply_local_resources_api(
    agent_id: int,
    payload: Nl2AgentApplyLocalResourcesRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Bulk-bind local tools and skills to the draft agent."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)

    try:
        return await apply_local_resources_batch(
            agent_id=agent_id,
            recommendation_batch_id=payload.recommendation_batch_id,
            tool_ids=payload.tool_ids,
            skill_ids=payload.skill_ids,
            tool_config_values=payload.tool_config_values,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/local-resources/register",
    response_model=Nl2AgentLocalRecommendationResponse,
)
async def register_local_resources_api(
    agent_id: int,
    payload: Nl2AgentRecommendationBatchRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await register_local_resource_recommendations(
            agent_id,
            payload.recommendation_batch_id,
            payload.tool_ids,
            payload.skill_ids,
            tenant_id,
            user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/local-resources/skip",
    response_model=Nl2AgentLocalSkipResponse,
)
async def skip_local_resources_api(
    agent_id: int,
    payload: Nl2AgentRecommendationSkipRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await skip_local_resource_recommendations(
            agent_id, payload.recommendation_batch_id, tenant_id, user_id
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/online-recommendations/register",
    response_model=Nl2AgentOnlineRecommendationResponse,
)
async def register_online_recommendations_api(
    agent_id: int,
    payload: Nl2AgentOnlineRecommendationBatchRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await register_online_resource_recommendations(
            agent_id,
            payload.recommendation_batch_id,
            payload.resource_type,
            payload.item_keys,
            tenant_id,
            user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/requirements/register",
    response_model=Nl2AgentRequirementsRegistrationResponse,
)
async def register_requirements_api(
    agent_id: int,
    payload: Nl2AgentRequirementsSummaryRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await register_requirements_review(
            agent_id,
            payload.model_dump(),
            tenant_id,
            user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/card-delivery",
    response_model=Nl2AgentCardDeliveryResponse,
    response_model_exclude_none=True,
)
async def report_card_delivery_api(
    agent_id: int,
    payload: Nl2AgentCardDeliveryRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await report_card_delivery(
            agent_id=agent_id,
            message_id=payload.message_id,
            card_type=payload.card_type,
            status=payload.status,
            card_key=payload.card_key,
            reason=payload.reason,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/requirements/confirm",
    response_model=Nl2AgentRequirementsConfirmationResponse,
)
async def confirm_requirements_api(
    agent_id: int,
    payload: Nl2AgentRequirementsConfirmRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await confirm_requirements_review(
            agent_id, payload.fingerprint, tenant_id, user_id
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/online-configuration/complete",
    response_model=Nl2AgentOnlineConfigurationResponse,
)
async def complete_online_configuration_api(
    agent_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await confirm_online_resource_configuration(agent_id, tenant_id, user_id)
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.get(
    "/session/{agent_id}/state",
    response_model=Nl2AgentSessionStateResponse,
    response_model_exclude_none=True,
)
async def get_session_state_api(
    agent_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await get_session_state(agent_id, tenant_id, user_id)
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.put(
    "/session/{agent_id}/identity",
    response_model=Nl2AgentIdentityResponse,
    response_model_exclude_none=True,
)
async def save_agent_identity_api(
    agent_id: int,
    payload: Nl2AgentIdentityRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await save_agent_identity(
            agent_id, payload.display_name, tenant_id, user_id
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/install-web-skill",
    response_model=Nl2AgentWebSkillInstallResponse,
)
async def install_web_skill_api(
    agent_id: int,
    payload: Nl2AgentInstallWebSkillRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Install a single official/web skill and bind it to the draft agent."""
    user_id, tenant_id, language = _current_user(authorization, http_request)

    try:
        return await install_web_skill(
            agent_id=agent_id,
            skill_id=payload.skill_id,
            skill_name=payload.skill_name,
            tenant_id=tenant_id,
            user_id=user_id,
            locale=language,
            config_values=payload.config_values,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.get(
    "/session/{agent_id}/web-skill/configuration",
    response_model=Nl2AgentWebSkillConfigurationResponse,
    response_model_exclude_none=True,
)
async def get_web_skill_configuration_api(
    agent_id: int,
    http_request: Request,
    skill_id: Optional[int] = Query(default=None, ge=1),
    skill_name: Optional[str] = Query(default=None, min_length=1, max_length=300),
    authorization: Optional[str] = Header(None),
):
    """Return authoritative configuration metadata for one trusted Skill."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return get_web_skill_configuration(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            skill_id=skill_id,
            skill_name=skill_name,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{agent_id}/finalize",
    response_model=Nl2AgentFinalizeResponse,
)
async def finalize_agent_api(
    agent_id: int,
    payload: Nl2AgentFinalizeRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Finalize the draft agent by generating its full prompt set."""
    user_id, tenant_id, language = _current_user(authorization, http_request)

    try:
        return await finalize_agent(
            agent_id=agent_id,
            user_id=user_id,
            tenant_id=tenant_id,
            description=payload.description,
            business_description=payload.business_description,
            duty_prompt=payload.duty_prompt,
            constraint_prompt=payload.constraint_prompt,
            few_shots_prompt=payload.few_shots_prompt,
            greeting_message=payload.greeting_message,
            example_questions=payload.example_questions,
            max_steps=payload.max_steps,
            requested_output_tokens=payload.requested_output_tokens,
            provide_run_summary=payload.provide_run_summary,
            verification_config=(
                payload.verification_config.model_dump()
                if payload.verification_config is not None
                else None
            ),
            enable_context_manager=payload.enable_context_manager,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc
