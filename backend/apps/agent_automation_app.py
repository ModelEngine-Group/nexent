import logging
from http import HTTPStatus
from typing import Annotated, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from consts.exceptions import UnauthorizedError
from services.agent_automation.errors import (
    AgentAutomationError,
    AutomationConversationAlreadyBoundError,
    AutomationNotFoundError,
)
from services.agent_automation.facade import agent_automation_facade
from services.agent_automation.models import (
    AutomationProposalConfirmRequest,
    AutomationProposalCreateRequest,
    AutomationProposalPatchRequest,
    AutomationResponse,
    AutomationTaskPatchRequest,
)
from utils.auth_utils import get_current_user_id

logger = logging.getLogger("agent_automation_app")

router = APIRouter(prefix="/agent/automations")
conversation_automation_router = APIRouter(prefix="/conversation")


def _get_current_user(authorization: Optional[str]) -> tuple[str, str]:
    try:
        return get_current_user_id(authorization)
    except UnauthorizedError as exc:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc)) from exc


def _map_error(exc: AgentAutomationError) -> HTTPException:
    if isinstance(exc, AutomationNotFoundError):
        status = HTTPStatus.NOT_FOUND
    elif isinstance(exc, AutomationConversationAlreadyBoundError):
        status = HTTPStatus.CONFLICT
    else:
        status = HTTPStatus.BAD_REQUEST
    return HTTPException(
        status_code=status,
        detail={
            "code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@router.post("/proposals", response_model=AutomationResponse)
async def create_proposal(request: AutomationProposalCreateRequest, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        data = await agent_automation_facade.create_proposal(request, tenant_id, user_id)
        return AutomationResponse(data=data)
    except AgentAutomationError as exc:
        raise _map_error(exc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to create automation proposal: %s", exc, exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/proposals/{proposal_id}/confirm", response_model=AutomationResponse)
async def confirm_proposal(
    proposal_id: int,
    request: AutomationProposalConfirmRequest | None = None,
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        data = await agent_automation_facade.confirm_proposal(
            proposal_id,
            request or AutomationProposalConfirmRequest(),
            tenant_id,
            user_id,
        )
        return AutomationResponse(data=data)
    except AgentAutomationError as exc:
        raise _map_error(exc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to confirm automation proposal: %s", exc, exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc))


@router.patch("/proposals/{proposal_id}", response_model=AutomationResponse)
async def update_proposal(
    proposal_id: int,
    request: AutomationProposalPatchRequest,
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        data = await agent_automation_facade.update_proposal(
            proposal_id,
            request,
            tenant_id,
            user_id,
        )
        return AutomationResponse(data=data)
    except AgentAutomationError as exc:
        raise _map_error(exc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to update automation proposal: %s", exc, exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("", response_model=AutomationResponse)
async def list_tasks(
    status: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=200),
    agent_name: Optional[str] = Query(default=None, max_length=200),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        return AutomationResponse(
            data=agent_automation_facade.list_tasks(
                tenant_id,
                user_id,
                status,
                search,
                agent_name,
                page,
                page_size,
            )
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to list automation tasks: %s", exc, exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/{task_id}", response_model=AutomationResponse)
async def get_task(task_id: int, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        return AutomationResponse(data=agent_automation_facade.get_task(task_id, tenant_id, user_id))
    except AgentAutomationError as exc:
        raise _map_error(exc)


@router.patch("/{task_id}", response_model=AutomationResponse)
async def patch_task(task_id: int, request: AutomationTaskPatchRequest, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        data = await agent_automation_facade.patch_task(task_id, request, tenant_id, user_id)
        return AutomationResponse(data=data)
    except AgentAutomationError as exc:
        raise _map_error(exc)


@router.post("/{task_id}/pause", response_model=AutomationResponse)
async def pause_task(task_id: int, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        return AutomationResponse(data=agent_automation_facade.pause_task(task_id, tenant_id, user_id))
    except AgentAutomationError as exc:
        raise _map_error(exc)


@router.post("/{task_id}/resume", response_model=AutomationResponse)
async def resume_task(task_id: int, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        return AutomationResponse(data=agent_automation_facade.resume_task(task_id, tenant_id, user_id))
    except AgentAutomationError as exc:
        raise _map_error(exc)


@router.post("/{task_id}/run", response_model=AutomationResponse)
async def run_task_now(task_id: int, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        return AutomationResponse(data=await agent_automation_facade.run_task_now(task_id, tenant_id, user_id))
    except AgentAutomationError as exc:
        raise _map_error(exc)


@router.delete("/{task_id}", response_model=AutomationResponse)
async def delete_task(task_id: int, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        return AutomationResponse(data=agent_automation_facade.delete_task(task_id, tenant_id, user_id))
    except AgentAutomationError as exc:
        raise _map_error(exc)


@router.get("/{task_id}/runs", response_model=AutomationResponse)
async def list_runs(
    task_id: int,
    authorization: Optional[str] = Header(None),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        return AutomationResponse(data=agent_automation_facade.list_runs(task_id, tenant_id, user_id, page, page_size))
    except AgentAutomationError as exc:
        raise _map_error(exc)


@router.post("/runs/{run_id}/cancel", response_model=AutomationResponse)
async def cancel_run(run_id: int, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        return AutomationResponse(data=agent_automation_facade.cancel_run(run_id, tenant_id, user_id))
    except AgentAutomationError as exc:
        raise _map_error(exc)


@router.delete("/runs/{run_id}", response_model=AutomationResponse)
async def delete_run(run_id: int, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        return AutomationResponse(data=agent_automation_facade.delete_run(run_id, tenant_id, user_id))
    except AgentAutomationError as exc:
        raise _map_error(exc)


@conversation_automation_router.get("/{conversation_id}/automation", response_model=AutomationResponse)
async def get_conversation_automation(conversation_id: int, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = _get_current_user(authorization)
        return AutomationResponse(
            data=agent_automation_facade.get_task_for_conversation(conversation_id, tenant_id, user_id)
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get conversation automation: %s", exc, exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc))
