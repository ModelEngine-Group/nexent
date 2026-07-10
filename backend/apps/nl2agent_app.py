"""HTTP API for the NL2AGENT conversational agent generator.

This router exposes session-management endpoints (start, apply-local-resources,
install-web-skill, finalize). The conversational chat itself runs through the
existing ``POST /agent/run`` endpoint with the NL2AGENT default agent_id, so no
new chat endpoint is needed here.
"""

import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Request
from starlette.responses import JSONResponse

from consts.exceptions import AgentRunException, UnauthorizedError
from consts.model import (
    Nl2AgentApplyLocalResourcesRequest,
    Nl2AgentFinalizeRequest,
    Nl2AgentInstallWebSkillRequest,
)
from services.nl2agent_service import (
    apply_local_resources_batch,
    finalize_agent,
    install_web_skill,
    start_session,
)
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/nl2agent")
logger = logging.getLogger("nl2agent_app")


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
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        )
    except Exception as exc:
        logger.exception(f"Failed to finalize agent {agent_id}: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to finalize agent.",
        )
