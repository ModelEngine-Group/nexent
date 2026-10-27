# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class AgentToolParamsRequest(BaseModel):
    """Request-scoped tool parameter overrides for a single agent."""

    tools: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Mapping from tool identifier to request-scoped override params",
    )


class ToolParamsRequest(BaseModel):
    """Request-scoped tool parameter overrides for main and managed agents."""

    agents: Dict[str, AgentToolParamsRequest] = Field(
        default_factory=dict,
        description="Mapping from agent identifier to tool parameter overrides",
    )


class ToolInstanceInfoRequest(BaseModel):
    tool_id: int
    agent_id: int
    params: Dict[str, Any]
    enabled: bool
    version_no: int = 0


class ToolInstanceSearchRequest(BaseModel):
    tool_id: int
    agent_id: int


class ToolSourceEnum(Enum):
    LOCAL = "local"
    MCP = "mcp"
    LANGCHAIN = "langchain"
    BUILTIN = "builtin"


class ToolInfo(BaseModel):
    name: str
    description: str
    description_zh: Optional[str] = None
    params: List
    source: str
    inputs: str
    output_type: str
    class_name: str
    usage: Optional[str]
    origin_name: Optional[str] = None
    category: Optional[str] = None
    labels: Optional[List[str]] = None
    is_user_selectable: bool = True


class ToolValidateRequest(BaseModel):
    """Request model for tool validation"""

    language: Literal["zh", "en"] = Field(
        "zh", description="Current frontend language for this validation run"
    )
    name: str = Field(..., description="Tool name to validate")
    source: str = Field(..., description="Tool source (local, mcp, langchain)")
    usage: Optional[str] = Field(None, description="Tool usage information")
    inputs: Optional[Dict[str, Any]] = Field(None, description="Tool inputs")
    params: Optional[Dict[str, Any]] = Field(
        None, description="Tool configuration parameters"
    )


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server"""

    command: str = Field(..., description="Command to run (e.g., 'npx')")
    args: List[str] = Field(default_factory=list, description="Command arguments")
    env: Optional[Dict[str, str]] = Field(
        None, description="Environment variables for the MCP server"
    )
    port: Optional[int] = Field(
        None, description="Host port to expose the MCP server on (e.g., 5020)"
    )
    image: Optional[str] = Field(
        None,
        description="Docker image for the MCP proxy container (optional, overrides MCP_DOCKER_IMAGE)",
    )


class MCPConfigRequest(BaseModel):
    """Request model for adding MCP servers from configuration"""

    mcpServers: Dict[str, MCPServerConfig] = Field(
        ..., description="Dictionary of MCP server configurations"
    )


class MCPUpdateRequest(BaseModel):
    """Request model for updating an existing MCP server"""

    current_service_name: str = Field(..., description="Current MCP service name")
    current_mcp_url: str = Field(..., description="Current MCP server URL")
    new_service_name: str = Field(..., description="New MCP service name")
    new_mcp_url: str = Field(..., description="New MCP server URL")
    new_authorization_token: Optional[str] = Field(
        None,
        description="New authorization token for MCP server authentication (e.g., Bearer token)",
    )
    custom_headers: Optional[Dict[str, Any]] = Field(
        None, description="Custom HTTP headers as JSON object"
    )


# ---------------------------------------------------------------------------
# MCP Management Data Models
# ---------------------------------------------------------------------------


class MCPSourceType(str, Enum):
    """MCP source type enumeration"""

    LOCAL = "local"
    MCP_REGISTRY = "mcp_registry"
    COMMUNITY = "community"


class AddMcpServiceRequest(BaseModel):
    """Request model for adding an MCP service"""

    name: str = Field(..., min_length=1, description="MCP service name")
    server_url: str = Field(..., min_length=1, description="MCP server URL")
    description: Optional[str] = Field(None, description="MCP service description")
    source: MCPSourceType = Field(
        default=MCPSourceType.LOCAL, description="MCP source type"
    )
    tags: List[str] = Field(default_factory=list, description="MCP tags")
    authorization_token: Optional[str] = Field(
        None, description="Authorization token for MCP server"
    )
    custom_headers: Optional[Dict[str, Any]] = Field(
        None, description="Custom HTTP headers as JSON object"
    )
    container_config: Optional[Dict[str, Any]] = Field(
        None, description="Container configuration"
    )
    container_port: Optional[int] = Field(
        None, ge=1, le=65535, description="Container host port"
    )
    registry_json: Optional[Dict[str, Any]] = Field(
        None, description="Registry metadata JSON"
    )
    config_json: Optional[Dict[str, Any]] = Field(
        None, description="MCP configuration JSON (e.g. OpenAPI spec for API-type MCP)"
    )
    market_id: Optional[int] = Field(None, gt=0, description="Linked market record ID")
    enabled: Optional[bool] = Field(
        default=False, description="Whether the MCP is enabled after creation"
    )
    group_ids: Optional[str] = Field(
        None, description="Comma-separated group IDs that can access this MCP"
    )
    ingroup_permission: Optional[str] = Field(
        None, description="Permission level: EDIT, READ_ONLY, PRIVATE"
    )
    shared_fields: Optional[Dict[str, Any]] = Field(
        None, description="JSON object of field-level sharing flags"
    )
    skip_health_check: Optional[bool] = Field(
        None, description="Skip MCP protocol health check (for community URL fallback)"
    )

    @field_validator(
        "name", "server_url", "description", "authorization_token", mode="before"
    )
    @classmethod
    def _strip_text(cls, value: Any):
        if isinstance(value, str):
            return value.strip()
        return value


class AddContainerMcpServiceRequest(BaseModel):
    """Request model for adding a container-based MCP service"""

    name: str = Field(..., min_length=1, description="MCP service name")
    description: Optional[str] = Field(None, description="MCP service description")
    source: MCPSourceType = Field(
        default=MCPSourceType.LOCAL, description="MCP source type"
    )
    tags: List[str] = Field(default_factory=list, description="MCP tags")
    authorization_token: Optional[str] = Field(
        None, description="Authorization token for MCP server"
    )
    registry_json: Optional[Dict[str, Any]] = Field(
        None, description="Registry metadata JSON"
    )
    market_id: Optional[int] = Field(None, gt=0, description="Linked market record ID")
    port: int = Field(..., ge=1, le=65535, description="Host port for the container")
    mcp_config: MCPConfigRequest = Field(..., description="MCP server configuration")
    group_ids: Optional[str] = Field(
        None, description="Comma-separated group IDs that can access this MCP"
    )
    ingroup_permission: Optional[str] = Field(
        None, description="Permission level: EDIT, READ_ONLY, PRIVATE"
    )
    shared_fields: Optional[Dict[str, Any]] = Field(
        None, description="JSON object of field-level sharing flags"
    )

    @field_validator("name", "description", "authorization_token", mode="before")
    @classmethod
    def _strip_text(cls, value: Any):
        if isinstance(value, str):
            return value.strip()
        return value


class UpdateMcpServiceRequest(BaseModel):
    """Request model for updating an MCP service"""

    mcp_id: int = Field(..., gt=0, description="MCP record ID")
    name: str = Field(..., min_length=1, description="New MCP service name")
    description: Optional[str] = Field(None, description="MCP service description")
    server_url: Optional[str] = Field(None, description="New MCP server URL")
    tags: List[str] = Field(default_factory=list, description="MCP tags")
    authorization_token: Optional[str] = Field(
        None, description="Authorization token for MCP server"
    )
    custom_headers: Optional[Dict[str, Any]] = Field(
        None, description="Custom HTTP headers as JSON object"
    )
    config_json: Optional[Dict[str, Any]] = Field(
        None, description="MCP configuration JSON"
    )
    version: Optional[str] = Field(None, description="MCP version")
    market_id: Optional[int] = Field(None, gt=0, description="Linked market record ID")
    group_ids: Optional[str] = Field(
        None, description="Comma-separated group IDs that can access this MCP"
    )
    ingroup_permission: Optional[str] = Field(
        None, description="Permission level: EDIT, READ_ONLY, PRIVATE"
    )
    shared_fields: Optional[Dict[str, Any]] = Field(
        None, description="JSON object of field-level sharing flags"
    )

    @field_validator(
        "name", "description", "authorization_token", "version", mode="before"
    )
    @classmethod
    def _strip_text(cls, value: Any):
        if isinstance(value, str):
            return value.strip()
        return value


class EnableMcpServiceRequest(BaseModel):
    """Request model for enabling an MCP service"""

    mcp_id: int = Field(..., gt=0, description="MCP record ID to enable")


class DisableMcpServiceRequest(BaseModel):
    """Request model for disabling an MCP service"""

    mcp_id: int = Field(..., gt=0, description="MCP record ID to disable")


class HealthcheckMcpServiceRequest(BaseModel):
    """Request model for checking MCP service health"""

    mcp_id: int = Field(..., gt=0, description="MCP record ID to health check")


class TestMcpConnectionRequest(BaseModel):
    """Request model for testing MCP server connectivity (lightweight handshake)"""

    server_url: str = Field(..., min_length=1, description="MCP server URL to test")
    authorization_token: Optional[str] = Field(
        None, description="Authorization token for MCP server"
    )
    custom_headers: Optional[Dict[str, Any]] = Field(
        None, description="Custom HTTP headers as JSON object"
    )


class ListMcpToolsRequest(BaseModel):
    """Request model for listing MCP service tools"""

    mcp_id: int = Field(..., gt=0, description="MCP record ID")


class PortConflictCheckRequest(BaseModel):
    """Request model for checking port availability"""

    port: int = Field(..., ge=1, le=65535, description="Port number to check")


class ListMcpServicesQuery(BaseModel):
    """Query parameters for listing MCP services"""

    tag: Optional[str] = Field(None, description="Filter by tag")

    @field_validator("tag", mode="before")
    @classmethod
    def _strip_tag(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class CommunityListRequest(BaseModel):
    """Request model for listing community MCP services"""

    search: Optional[str] = Field(None, description="Search keyword")
    tag: Optional[str] = Field(None, description="Filter by tag")
    transport_type: Optional[str] = Field(
        None, description="Filter by transport: url or container"
    )
    cursor: Optional[str] = Field(None, description="Pagination cursor")
    page: Optional[int] = Field(None, ge=1, description="Offset pagination page")
    limit: int = Field(default=30, ge=1, le=100, description="Items per page")

    @field_validator("search", "tag", "cursor", "transport_type", mode="before")
    @classmethod
    def _strip_text(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class CommunityReviewListRequest(CommunityListRequest):
    """Request model for listing MCP community review submissions"""

    status: Optional[str] = Field(None, description="Review status filter")

    @field_validator("status", mode="before")
    @classmethod
    def _strip_status(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class CommunityReviewActionRequest(BaseModel):
    """Request model for approving or rejecting an MCP community submission"""

    review_id: int = Field(..., gt=0, description="Review record ID")
    content: Optional[str] = Field(None, description="Review opinion on approve/reject")

    @field_validator("content", mode="before")
    @classmethod
    def _strip_review_content(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class CommunityPublishRequest(BaseModel):
    """Publish a local MCP to the community; optional fields override the snapshot."""

    mcp_id: int = Field(..., gt=0, description="MCP record ID to publish")
    name: Optional[str] = Field(None, description="Community display name override")
    description: Optional[str] = Field(None, description="Description override")
    tags: Optional[List[str]] = Field(None, description="Tags override")
    mcp_server: Optional[str] = Field(
        None,
        max_length=500,
        description="Remote MCP server URL override (URL / HTTP / SSE transports)",
    )
    config_json: Optional[Dict[str, Any]] = Field(
        None, description="Container MCP configuration JSON override"
    )
    group_ids: Optional[List[int]] = Field(
        None, description="Group IDs that can access this MCP"
    )
    ingroup_permission: Optional[str] = Field(
        None, description="Permission level: EDIT, READ_ONLY, PRIVATE"
    )
    shared_fields: Optional[Dict[str, Any]] = Field(
        None, description="JSON object of field-level sharing flags"
    )
    content: Optional[str] = Field(None, description="Listing note on submit")

    @field_validator("name", "description", "mcp_server", "content", mode="before")
    @classmethod
    def _strip_publish_optional_text(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class CommunityUpdateRequest(BaseModel):
    """Request model for updating community MCP service"""

    market_id: int = Field(..., gt=0, description="Market record ID")
    name: Optional[str] = Field(
        default=None, min_length=1, description="New MCP service name"
    )
    description: Optional[str] = Field(None, description="MCP service description")
    tags: List[str] = Field(default_factory=list, description="MCP tags")
    registry_json: Optional[Dict[str, Any]] = Field(
        None, description="Registry metadata JSON"
    )
    mcp_server: Optional[str] = Field(
        None, max_length=500, description="MCP server URL"
    )
    transport_type: Optional[str] = Field(None, description="Transport type")
    config_json: Optional[Dict[str, Any]] = Field(
        None,
        description="Container MCP configuration JSON (omit to leave unchanged)",
    )
    group_ids: Optional[List[int]] = Field(
        None, description="Group IDs that can access this MCP"
    )
    ingroup_permission: Optional[str] = Field(
        None, description="Permission level: EDIT, READ_ONLY, PRIVATE"
    )
    shared_fields: Optional[Dict[str, Any]] = Field(
        None, description="JSON object of field-level sharing flags"
    )
    content: Optional[str] = Field(None, description="Listing note on resubmit")

    @field_validator(
        "name", "description", "mcp_server", "transport_type", "content", mode="before"
    )
    @classmethod
    def _strip_text(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class CommunityStatusUpdateRequest(BaseModel):
    """Request model for changing MCP market listing status (PATCH)."""

    status: str = Field(
        ..., description="New status: shared / rejected / not_shared / pending_review"
    )
    content: Optional[str] = Field(
        None, description="Review opinion or resubmit listing note"
    )

    @field_validator("content", mode="before")
    @classmethod
    def _strip_status_content(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class DeleteMcpServiceRequest(BaseModel):
    """Request model for deleting an MCP service"""

    mcp_id: int = Field(..., gt=0, description="MCP record ID to delete")
