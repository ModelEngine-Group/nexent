"""
A2UI API endpoints for user action submission, interaction queries,
and interaction cancellation.

Provides the HTTP interface between the frontend (A2UI renderer) and the
backend HITL service so that user actions can be routed back to the
running agent conversation.
"""

import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from services.a2ui_hitl_service import A2UIHITLService

logger = logging.getLogger("a2ui_app")

a2ui_router = APIRouter(prefix="/api/a2ui", tags=["A2UI"])


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------


class ActionSubmitRequest(BaseModel):
    interaction_id: str
    action: str = "quick_reply"
    payload: Optional[dict] = None
    user_id: Optional[str] = None


class ActionSubmitResponse(BaseModel):
    status: str = "ok"
    interaction_id: str


class InteractionDetail(BaseModel):
    interaction_id: str
    status: str
    response: Optional[dict] = None
    question: str = ""
    payload: Optional[dict] = None
    created_at: Optional[float] = None


class InteractionListResponse(BaseModel):
    status: str = "ok"
    interactions: list[InteractionDetail] = []


class CancelResponse(BaseModel):
    status: str = "ok"


# ------------------------------------------------------------------
# API endpoints
# ------------------------------------------------------------------


@a2ui_router.post(
    "/action",
    response_model=ActionSubmitResponse,
    summary="Submit user action response",
    description="Submit a user action response to a pending HITL interaction.",
)
async def submit_action(
    request: ActionSubmitRequest,
    authorization: Optional[str] = Header(None),
) -> ActionSubmitResponse:
    """Submit a user action response to a pending interaction.

    The frontend calls this endpoint when the user interacts with an
    A2UI component (button click, form submit, rating change, etc.).
    """
    service = A2UIHITLService.get_instance()
    interaction = service.get_interaction(request.interaction_id)

    if interaction is None:
        logger.warning(
            "submit_action: interaction %s not found",
            request.interaction_id,
        )
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Interaction not found",
        )

    if interaction.status != "pending":
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Interaction is {interaction.status}",
        )

    if request.user_id and interaction.user_id != request.user_id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Not authorized",
        )

    success = service.submit_response(
        request.interaction_id,
        {
            "interaction_id": request.interaction_id,
            "action": request.action,
            "payload": request.payload or {},
        },
    )

    if not success:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to submit response",
        )

    logger.info(
        "Action submitted for interaction %s: action=%s",
        request.interaction_id,
        request.action,
    )
    return ActionSubmitResponse(
        status="ok", interaction_id=request.interaction_id
    )


@a2ui_router.get(
    "/interactions/{conversation_id}",
    response_model=InteractionListResponse,
    summary="Get pending interactions for a conversation",
    description="Retrieve all pending HITL interactions for a given conversation.",
)
async def get_pending_interactions(
    conversation_id: str,
    user_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
) -> InteractionListResponse:
    """Return all pending interactions for the given conversation.

    Used by the frontend to recover interaction state after a
    reconnection or page refresh.
    """
    service = A2UIHITLService.get_instance()
    interactions = service.get_pending_interactions(
        conversation_id=conversation_id,
        user_id=user_id,
    )

    details = [
        InteractionDetail(
            interaction_id=i.interaction_id,
            status=i.status.value,
            response=i.response,
            question=i.question,
            payload=i.payload,
            created_at=i.created_at,
        )
        for i in interactions
    ]

    return InteractionListResponse(
        status="ok", interactions=details
    )


@a2ui_router.delete(
    "/interactions/{interaction_id}",
    response_model=CancelResponse,
    summary="Cancel a pending interaction",
    description="Cancel a pending HITL interaction by its ID.",
)
async def cancel_interaction(
    interaction_id: str,
    authorization: Optional[str] = Header(None),
) -> CancelResponse:
    """Cancel a pending interaction.

    The agent will receive a ``None`` response from
    :func:`A2UIHITLService.wait_for_response` and can then choose
    to skip the step or prompt the user again.
    """
    service = A2UIHITLService.get_instance()
    if not service.cancel_interaction(interaction_id):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Interaction not found",
        )

    logger.info("Cancelled interaction %s via API", interaction_id)
    return CancelResponse(status="ok")