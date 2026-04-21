"""
A2A Server internal management endpoints.

These endpoints are for internal use only (user authentication required).
They are NOT registered to any FastAPI app - only used by internal code.
"""
import logging
from typing import Any, Dict, Optional
from typing_extensions import Annotated

from http import HTTPStatus

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.a2a_server_service import a2a_server_service, EndpointNotFoundError
from utils.auth_utils import get_current_user_info

logger = logging.getLogger("a2a_server_app")

router = APIRouter(prefix="/a2a", tags=["A2A Server Internal"])


class A2AServerSettings(BaseModel):
    """A2A Server settings for an agent."""
    is_enabled: Optional[bool] = False
    card_overrides: Optional[Dict[str, Any]] = None


@router.post("/management/agents/{agent_id}/enable")
async def enable_a2a_server(
    agent_id: int,
    settings: A2AServerSettings,
    authorization: Annotated[Optional[str], Header()] = None,
    http_request: Annotated[Request, Request] = None
):
    """Enable A2A Server for an agent.

    Authentication: User Bearer Token (internal use only)
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        result = a2a_server_service.enable_a2a(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            card_overrides=settings.card_overrides
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": result}
        )

    except EndpointNotFoundError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Enable A2A server failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to enable A2A server"
        )


@router.post("/management/agents/{agent_id}/disable")
async def disable_a2a_server(
    agent_id: int,
    authorization: Annotated[Optional[str], Header()] = None,
    http_request: Annotated[Request, Request] = None
):
    """Disable A2A Server for an agent.

    Authentication: User Bearer Token (internal use only)
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        a2a_server_service.disable_a2a(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "message": "A2A Server disabled"}
        )

    except EndpointNotFoundError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Disable A2A server failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to disable A2A server"
        )


@router.get("/management/agents/{agent_id}/settings")
async def get_a2a_settings(
    agent_id: int,
    authorization: Annotated[Optional[str], Header()] = None,
    http_request: Annotated[Request, Request] = None
):
    """Get A2A Server settings for an agent.

    Authentication: User Bearer Token (internal use only)
    """
    try:
        _, tenant_id, _ = get_current_user_info(authorization, http_request)

        registration = a2a_server_service.get_registration(agent_id, tenant_id)

        if not registration:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"No A2A Server registration for agent {agent_id}"
            )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": registration}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get A2A settings failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get A2A settings"
        )


@router.put("/management/agents/{agent_id}/settings")
async def update_a2a_settings(
    agent_id: int,
    settings: A2AServerSettings,
    authorization: Annotated[Optional[str], Header()] = None,
    http_request: Annotated[Request, Request] = None
):
    """Update A2A Server settings for an agent.

    Authentication: User Bearer Token (internal use only)
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        result = a2a_server_service.update_settings(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            is_enabled=settings.is_enabled,
            card_overrides=settings.card_overrides
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": result}
        )

    except EndpointNotFoundError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Update A2A settings failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update A2A settings"
        )


@router.get("/management/agents")
async def list_a2a_agents(
    authorization: Annotated[Optional[str], Header()] = None,
    http_request: Annotated[Request, Request] = None
):
    """List all A2A Server agents for the current tenant.

    Authentication: User Bearer Token (internal use only)
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        registrations = a2a_server_service.list_registrations(
            tenant_id=tenant_id,
            user_id=user_id
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": registrations}
        )

    except Exception as e:
        logger.error(f"List A2A agents failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list A2A agents"
        )
