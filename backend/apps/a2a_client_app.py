"""
A2A Client API endpoints.

These endpoints allow users to discover and manage external A2A agents.
Used internally for configuring A2A sub-agents.
"""
import logging
from typing import List, Optional
from http import HTTPStatus

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from services.a2a_client_service import (
    a2a_client_service,
    AgentDiscoveryError,
    AgentCallError,
)
from services.a2a_server_service import a2a_server_service
from database import a2a_agent_db
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/a2a/client", tags=["A2A Client"])
logger = logging.getLogger("a2a_client_app")


class DiscoverFromUrlRequest(BaseModel):
    """Request to discover external A2A agent from URL."""
    url: str
    name: Optional[str] = None


class DiscoverFromNacosRequest(BaseModel):
    """Request to discover external A2A agents from Nacos."""
    nacos_config_id: str
    agent_names: List[str]
    namespace: Optional[str] = "public"


class CallExternalAgentRequest(BaseModel):
    """Request to call an external A2A agent."""
    agent_id: int
    message: dict
    stream: Optional[bool] = False


class UpdateAgentProtocolRequest(BaseModel):
    """Request to update the protocol type for an external A2A agent."""
    protocol_type: str = Field(
        description="Protocol type to use: JSONRPC, HTTP+JSON, or GRPC"
    )


# =============================================================================
# External Agent Discovery
# =============================================================================

@router.post("/discover/url")
async def discover_from_url(
    request: DiscoverFromUrlRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Discover an external A2A agent from URL.

    Fetches the Agent Card from the URL and caches it.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        result = await a2a_client_service.discover_from_url(
            url=request.url,
            tenant_id=tenant_id,
            user_id=user_id
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": result}
        )

    except AgentDiscoveryError as e:
        logger.error(f"Agent discovery failed: {e}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Discover from URL failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to discover agent"
        )


@router.post("/discover/nacos")
async def discover_from_nacos(
    request: DiscoverFromNacosRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Discover external A2A agents from Nacos service registry.

    Uses the specified Nacos config to discover agents by name.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        results = await a2a_client_service.discover_from_nacos(
            nacos_config_id=request.nacos_config_id,
            agent_names=request.agent_names,
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=request.namespace
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": results}
        )

    except AgentDiscoveryError as e:
        logger.error(f"Nacos discovery failed: {e}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Discover from Nacos failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to discover agents from Nacos"
        )


# =============================================================================
# External Agent Management
# =============================================================================

@router.get("/agents")
async def list_external_agents(
    source_type: Optional[str] = Query(None, description="Filter by source type: url or nacos"),
    is_available: Optional[bool] = Query(None, description="Filter by availability"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """List all discovered external A2A agents for the current tenant."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        agents = a2a_client_service.list_external_agents(
            tenant_id=tenant_id,
            source_type=source_type,
            is_available=is_available
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": agents}
        )

    except Exception as e:
        logger.error(f"List agents failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list agents"
        )


@router.get("/agents/{external_agent_id}")
async def get_external_agent(
    external_agent_id: int,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Get details of a specific external A2A agent."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        agent = a2a_client_service.get_external_agent(external_agent_id, tenant_id)

        if not agent:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Agent {external_agent_id} not found"
            )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": agent}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get agent failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get agent"
        )


@router.post("/agents/{external_agent_id}/refresh")
async def refresh_agent_card(
    external_agent_id: int,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Refresh the cached Agent Card for an external agent."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        result = await a2a_client_service.refresh_agent_card(
            external_agent_id=external_agent_id,
            tenant_id=tenant_id,
            user_id=user_id
        )

        if not result:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Agent {external_agent_id} not found"
            )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": result}
        )

    except HTTPException:
        raise
    except AgentDiscoveryError as e:
        logger.error(f"Refresh failed: {e}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Refresh agent failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to refresh agent"
        )


@router.delete("/agents/{external_agent_id}")
async def delete_external_agent(
    external_agent_id: int,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Delete a discovered external A2A agent."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        result = a2a_client_service.delete_external_agent(external_agent_id, tenant_id)

        if not result:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Agent {external_agent_id} not found"
            )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "message": "Agent deleted"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete agent failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete agent"
        )


@router.put("/agents/{external_agent_id}/protocol")
async def update_agent_protocol(
    external_agent_id: int,
    request: UpdateAgentProtocolRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Update the protocol type for an external A2A agent.

    Args:
        external_agent_id: The external agent database ID.
        request: Request containing the new protocol type.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        result = a2a_client_service.update_agent_protocol(
            external_agent_id=external_agent_id,
            tenant_id=tenant_id,
            protocol_type=request.protocol_type
        )

        if not result:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Agent {external_agent_id} not found"
            )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": result}
        )

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Invalid protocol type: {e}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Update agent protocol failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update agent protocol"
        )


@router.get("/agents/{external_agent_id}/health")
async def check_agent_health(
    external_agent_id: int,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Check the health of an external A2A agent."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        result = await a2a_client_service.check_agent_health(external_agent_id, tenant_id)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": result}
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to check agent health"
        )


@router.post("/agents/{external_agent_id}/test")
async def test_agent(
    external_agent_id: int,
    request: CallExternalAgentRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Test connection to an external A2A agent."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        if request.stream:
            return StreamingResponse(
                a2a_client_service.call_agent_streaming(
                    external_agent_id=external_agent_id,
                    tenant_id=tenant_id,
                    message=request.message
                ),
                media_type="text/event-stream"
            )
        else:
            result = await a2a_client_service.call_agent(
                external_agent_id=external_agent_id,
                tenant_id=tenant_id,
                message=request.message
            )

            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={"status": "success", "data": result}
            )

    except AgentCallError as e:
        logger.error(f"Test call failed: {e}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test agent failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to test agent"
        )


# =============================================================================
# External Agent Relations (Sub-agent)
# =============================================================================

from pydantic import BaseModel


class AddRelationRequest(BaseModel):
    """Request body for adding a relation between local agent and external A2A agent."""
    local_agent_id: int
    external_agent_id: int


@router.post("/relations")
async def add_external_agent_relation(
    request_body: AddRelationRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Add a relation between a local agent and an external A2A agent.

    This allows the local agent to call the external agent as a sub-agent.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        result = a2a_agent_db.add_external_agent_relation(
            local_agent_id=request_body.local_agent_id,
            external_agent_id=request_body.external_agent_id,
            tenant_id=tenant_id,
            user_id=user_id
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": result}
        )

    except ValueError as e:
        logger.error(f"Add relation failed: {e}")
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Add relation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to add relation"
        )


@router.delete("/relations")
async def remove_external_agent_relation(
    local_agent_id: int = Query(..., description="Local agent ID"),
    external_agent_id: int = Query(..., description="External agent ID"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Remove a relation between a local agent and an external A2A agent."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        result = a2a_agent_db.remove_external_agent_relation(
            local_agent_id=local_agent_id,
            external_agent_id=external_agent_id,
            tenant_id=tenant_id
        )

        if not result:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail="Relation not found"
            )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "message": "Relation removed"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Remove relation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to remove relation"
        )


@router.get("/relations/{local_agent_id}")
async def list_external_relations(
    local_agent_id: int,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """List all external A2A agent relations for a local agent."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        relations = a2a_agent_db.list_external_relations_by_local_agent(
            local_agent_id=local_agent_id,
            tenant_id=tenant_id
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": relations}
        )

    except Exception as e:
        logger.error(f"List relations failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list relations"
        )


@router.get("/sub-agents/{local_agent_id}")
async def get_external_sub_agents(
    local_agent_id: int,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Get external A2A agents configured as sub-agents for a local agent.

    Returns agent details including URL and cached Agent Card.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        agents = a2a_agent_db.query_external_sub_agents(
            local_agent_id=local_agent_id,
            tenant_id=tenant_id
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": agents}
        )

    except Exception as e:
        logger.error(f"Get sub-agents failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get sub-agents"
        )


# =============================================================================
# Nacos Config Management
# =============================================================================

class CreateNacosConfigRequest(BaseModel):
    """Request to create a Nacos config."""
    name: str
    nacos_addr: str
    nacos_username: Optional[str] = None
    nacos_password: Optional[str] = None
    namespace_id: Optional[str] = "public"
    description: Optional[str] = None


@router.post("/nacos-configs")
async def create_nacos_config(
    request: CreateNacosConfigRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Create a Nacos configuration for external A2A agent discovery."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        result = a2a_agent_db.create_nacos_config(
            name=request.name,
            nacos_addr=request.nacos_addr,
            tenant_id=tenant_id,
            user_id=user_id,
            nacos_username=request.nacos_username,
            nacos_password=request.nacos_password,
            namespace_id=request.namespace_id,
            description=request.description
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": result}
        )

    except Exception as e:
        logger.error(f"Create Nacos config failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to create Nacos config"
        )


@router.get("/nacos-configs")
async def list_nacos_configs(
    is_active: Optional[bool] = Query(None),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """List all Nacos configurations for the current tenant."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        configs = a2a_agent_db.list_nacos_configs(
            tenant_id=tenant_id,
            is_active=is_active
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": configs}
        )

    except Exception as e:
        logger.error(f"List Nacos configs failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list Nacos configs"
        )


@router.get("/nacos-configs/{config_id}")
async def get_nacos_config(
    config_id: str,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Get a specific Nacos configuration."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        config = a2a_agent_db.get_nacos_config_by_id(config_id, tenant_id)

        if not config:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Nacos config {config_id} not found"
            )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "data": config}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get Nacos config failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get Nacos config"
        )


@router.delete("/nacos-configs/{config_id}")
async def delete_nacos_config(
    config_id: str,
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """Delete a Nacos configuration."""
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, http_request)

        result = a2a_agent_db.delete_nacos_config(config_id, tenant_id)

        if not result:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Nacos config {config_id} not found"
            )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"status": "success", "message": "Nacos config deleted"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete Nacos config failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to delete Nacos config"
        )
