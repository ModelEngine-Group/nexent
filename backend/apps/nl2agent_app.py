"""HTTP API for the NL2AGENT conversational agent generator.

This router exposes session-management endpoints (start, apply-local-resources,
install-web-skill, finalize). The conversational chat itself runs through the
existing ``POST /agent/run`` endpoint with the NL2AGENT default agent_id, so no
new chat endpoint is needed here.
"""

import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from starlette.responses import JSONResponse

from consts.exceptions import AgentRunException, UnauthorizedError
from consts.model import (
    Nl2AgentApplyLocalResourcesRequest,
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
from services.nl2agent_service import (
    apply_local_resources_batch,
    confirm_online_resource_configuration,
    confirm_requirements_review,
    finalize_agent,
    install_web_skill,
    bind_mcp_tools,
    install_recommended_mcp,
    get_session_state,
    register_local_resource_recommendations,
    register_online_resource_recommendations,
    register_requirements_review,
    save_agent_identity,
    select_models,
    skip_mcp_tool_binding,
    skip_local_resource_recommendations,
    start_session,
)
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/nl2agent")
logger = logging.getLogger("nl2agent_app")


def _current_user(authorization, http_request):
    return get_current_user_info(authorization, http_request)


def _session_http_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if "draft agent not found" in message:
        return HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=message)
    if any(
        marker in message
        for marker in (
            "before finalizing",
            "cannot be empty",
            "incomplete",
            "Select a primary LLM",
            "Reopen the model-selection card",
            "Apply or skip",
            "Show the local resource",
            "Show online resource",
            "Online recommendation batch contents",
            "before completing online configuration",
            "Complete the online resource",
            "display name is missing",
            "Requirements summary",
            "Confirm the requirements summary",
            "requirements summary is stale",
            "requirements summary is not awaiting confirmation",
        )
    ):
        return HTTPException(status_code=HTTPStatus.CONFLICT, detail=message)
    if isinstance(exc, AgentRunException):
        return HTTPException(status_code=HTTPStatus.CONFLICT, detail=message)
    logger.exception("NL2AGENT session operation failed")
    return HTTPException(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        detail="Failed to load or update NL2AGENT session state.",
    )


@router.put("/session/{agent_id}/models")
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


@router.post("/session/{agent_id}/mcp/install")
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


@router.post("/session/{agent_id}/mcp/{mcp_id}/bind-tools")
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


@router.post("/session/{agent_id}/mcp/{mcp_id}/skip-tools")
async def skip_mcp_tools_api(
    agent_id: int,
    mcp_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    _, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await skip_mcp_tool_binding(agent_id, mcp_id, tenant_id)
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post("/session/start")
async def start_session_api(
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Start a new NL2AGENT session: creates a draft agent and a conversation.

    Returns ``{"agent_id": int, "conversation_id": int, "draft_name": str}``.
    The frontend then opens the chat page with the NL2AGENT default agent_id
    and this conversation_id.
    """
    try:
        user_id, tenant_id, language = get_current_user_info(
            authorization, http_request
        )
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc)
        )

    try:
        result = await start_session(
            user_id=user_id, tenant_id=tenant_id, language=language
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AgentRunException as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        )
    except Exception as exc:
        logger.exception(f"Failed to start NL2AGENT session: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to start NL2AGENT session.",
        )


@router.post("/session/{agent_id}/apply-local-resources")
async def apply_local_resources_api(
    agent_id: int,
    payload: Nl2AgentApplyLocalResourcesRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Bulk-bind local tools and skills to the draft agent."""
    try:
        user_id, tenant_id, _ = get_current_user_info(
            authorization, http_request
        )
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc)
        )

    try:
        result = await apply_local_resources_batch(
            agent_id=agent_id,
            recommendation_batch_id=payload.recommendation_batch_id,
            tool_ids=payload.tool_ids,
            skill_ids=payload.skill_ids,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AgentRunException as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        )
    except Exception as exc:
        logger.exception(f"Failed to apply local resources: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to apply local resources.",
        )


@router.post("/session/{agent_id}/local-resources/register")
async def register_local_resources_api(
    agent_id: int,
    payload: Nl2AgentRecommendationBatchRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    _, tenant_id, _ = _current_user(authorization, http_request)
    return await register_local_resource_recommendations(
        agent_id,
        payload.recommendation_batch_id,
        payload.tool_ids,
        payload.skill_ids,
        tenant_id,
    )


@router.post("/session/{agent_id}/local-resources/skip")
async def skip_local_resources_api(
    agent_id: int,
    payload: Nl2AgentRecommendationSkipRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    _, tenant_id, _ = _current_user(authorization, http_request)
    return await skip_local_resource_recommendations(
        agent_id, payload.recommendation_batch_id, tenant_id
    )


@router.post("/session/{agent_id}/online-recommendations/register")
async def register_online_recommendations_api(
    agent_id: int,
    payload: Nl2AgentOnlineRecommendationBatchRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    _, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await register_online_resource_recommendations(
            agent_id,
            payload.recommendation_batch_id,
            payload.resource_type,
            payload.item_keys,
            tenant_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post("/session/{agent_id}/requirements/register")
async def register_requirements_api(
    agent_id: int,
    payload: Nl2AgentRequirementsSummaryRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    _, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await register_requirements_review(
            agent_id,
            payload.model_dump(),
            tenant_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post("/session/{agent_id}/requirements/confirm")
async def confirm_requirements_api(
    agent_id: int,
    payload: Nl2AgentRequirementsConfirmRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    _, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await confirm_requirements_review(
            agent_id, payload.fingerprint, tenant_id
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post("/session/{agent_id}/online-configuration/complete")
async def complete_online_configuration_api(
    agent_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    _, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await confirm_online_resource_configuration(agent_id, tenant_id)
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.get("/session/{agent_id}/state")
async def get_session_state_api(
    agent_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    _, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await get_session_state(agent_id, tenant_id)
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.put("/session/{agent_id}/identity")
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


@router.post("/session/{agent_id}/install-web-skill")
async def install_web_skill_api(
    agent_id: int,
    payload: Nl2AgentInstallWebSkillRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Install a single official/web skill into the tenant."""
    try:
        user_id, tenant_id, language = get_current_user_info(
            authorization, http_request
        )
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc)
        )

    try:
        result = await install_web_skill(
            agent_id=agent_id,
            skill_id=payload.skill_id,
            skill_name=payload.skill_name,
            tenant_id=tenant_id,
            user_id=user_id,
            locale=language,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AgentRunException as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        )
    except Exception as exc:
        logger.exception(f"Failed to install web skill: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to install web skill.",
        )


@router.post("/session/{agent_id}/finalize")
async def finalize_agent_api(
    agent_id: int,
    payload: Nl2AgentFinalizeRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Finalize the draft agent by generating its full prompt set."""
    try:
        user_id, tenant_id, language = get_current_user_info(
            authorization, http_request
        )
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc)
        )

    try:
        result = await finalize_agent(
            agent_id=agent_id,
            user_id=user_id,
            tenant_id=tenant_id,
            name=payload.name,
            display_name=payload.display_name,
            description=payload.description,
            business_logic_model_id=payload.business_logic_model_id,
            model_ids=payload.model_ids,
            business_description=payload.business_description,
            prompt_template_id=payload.prompt_template_id,
            duty_prompt=payload.duty_prompt,
            constraint_prompt=payload.constraint_prompt,
            few_shots_prompt=payload.few_shots_prompt,
            greeting_message=payload.greeting_message,
            example_questions=payload.example_questions,
            max_steps=payload.max_steps,
            requested_output_tokens=payload.requested_output_tokens,
            provide_run_summary=payload.provide_run_summary,
            verification_config=payload.verification_config,
            enable_context_manager=payload.enable_context_manager,
            tool_ids=payload.tool_ids,
            skill_ids=payload.skill_ids,
            sub_agent_ids=payload.sub_agent_ids,
            tool_configs=payload.tool_configs,
            skill_configs=payload.skill_configs,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AgentRunException as exc:
        raise _session_http_error(exc) from exc
    except Exception as exc:
        logger.exception(f"Failed to finalize agent {agent_id}: {exc}")
        raise _session_http_error(exc) from exc
