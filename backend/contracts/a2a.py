# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pydantic models for A2A protocol."""

from dataclasses import dataclass, field
from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, Field


@dataclass
class A2AExecutionContext:
    """Context for A2A task execution."""

    task_id: str
    endpoint_id: str
    token_id: Optional[int] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_debug: bool = False


class A2AMessageContent(BaseModel):
    """A2A message content structure."""

    type: str = Field(
        default="text", description="Content type: text, image, file, etc."
    )
    text: Optional[str] = Field(default=None, description="Text content")


class A2AMessage(BaseModel):
    """A2A message structure."""

    role: str = Field(description="Message sender role: user or agent")
    content: A2AMessageContent = Field(description="Message content")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional metadata"
    )


class A2ATaskStatus(BaseModel):
    """A2A task status."""

    state: str = Field(description="Task state: working, completed, failed, canceled")
    message: Optional[A2AMessage] = Field(default=None, description="Status message")
    tokens: Optional[Dict[str, int]] = Field(default=None, description="Token usage")


class A2ATask(BaseModel):
    """A2A task structure."""

    id: str = Field(description="Unique task identifier")
    status: Optional[A2ATaskStatus] = Field(default=None, description="Task status")
    artifacts: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Task artifacts"
    )


class A2ATaskEvent(BaseModel):
    """A2A task event (for streaming)."""

    kind: str = Field(
        description="Event type: taskProgress, taskArtifact, taskStatusUpdate"
    )
    task_id: str = Field(description="Task ID")
    status: Optional[A2ATaskStatus] = Field(default=None, description="Updated status")
    content: Optional[str] = Field(default=None, description="Progress content")
    artifact: Optional[Dict[str, Any]] = Field(
        default=None, description="Artifact data"
    )


class A2AAgentProvider(BaseModel):
    """A2A agent provider information."""

    organization: str = Field(description="Provider organization name")
    url: Optional[str] = Field(default=None, description="Provider URL")


class A2AAgentCapabilities(BaseModel):
    """A2A agent capabilities."""

    streaming: bool = Field(default=False, description="Supports streaming")
    pushNotifications: bool = Field(
        default=False, description="Supports push notifications"
    )
    stateTransitionReports: bool = Field(
        default=False, description="Supports state transition reports"
    )
    artifacts: bool = Field(default=False, description="Supports artifacts")
    supportedTransportTypes: List[str] = Field(
        default_factory=list,
        description="Supported transport types: http-streaming, http-polling",
    )
    protocolVersion: str = Field(default="1.0", description="A2A protocol version")


class A2ASupportedInterface(BaseModel):
    """A2A supported interface for a specific protocol."""

    protocolBinding: str = Field(
        description="Protocol binding: http-json-rpc, rest, grpc"
    )
    url: str = Field(description="Endpoint URL for this protocol")
    protocolVersion: str = Field(default="1.0", description="Protocol version")


class A2AAgentSkill(BaseModel):
    """A2A agent skill definition."""

    id: str = Field(description="Skill unique identifier")
    name: str = Field(description="Skill display name")
    description: Optional[str] = Field(default=None, description="Skill description")
    tags: List[str] = Field(default_factory=list, description="Skill tags")
    examples: List[str] = Field(default_factory=list, description="Usage examples")
    inputModes: List[str] = Field(
        default_factory=list, description="Supported input MIME types"
    )
    outputModes: List[str] = Field(
        default_factory=list, description="Supported output MIME types"
    )


class A2AAgentCard(BaseModel):
    """A2A Agent Card for discovery (v1.0 specification).

    This is the standard A2A discovery format.
    External agents provide this card at /.well-known/agent-{id}.json
    """

    name: str = Field(description="Agent display name")
    description: Optional[str] = Field(default=None, description="Agent description")
    version: Optional[str] = Field(
        default=None, description="Agent version, e.g., 1.2.0"
    )

    # Provider info
    provider: Optional[A2AAgentProvider] = Field(
        default=None, description="Agent provider information"
    )
    documentationUrl: Optional[str] = Field(
        default=None, description="Documentation URL"
    )

    # Capabilities
    capabilities: A2AAgentCapabilities = Field(
        default_factory=A2AAgentCapabilities, description="Agent capabilities"
    )

    # I/O modes
    defaultInputModes: List[str] = Field(
        default_factory=lambda: ["text/plain"],
        description="Default supported input MIME types",
    )
    defaultOutputModes: List[str] = Field(
        default_factory=lambda: ["text/plain"],
        description="Default supported output MIME types",
    )

    # Skills
    skills: List[A2AAgentSkill] = Field(
        default_factory=list, description="Agent skills"
    )

    # Endpoints - multiple protocols supported
    supportedInterfaces: List[A2ASupportedInterface] = Field(
        default_factory=list, description="All supported protocol endpoints"
    )

    # Legacy URL field (maps to http-json-rpc interface)
    url: Optional[str] = Field(
        default=None, description="Base URL for the agent (http-json-rpc fallback)"
    )

    # Security
    securitySchemes: Dict[str, Any] = Field(
        default_factory=dict, description="Security schemes"
    )
    securityRequirements: List[Any] = Field(
        default_factory=list, description="Security requirements"
    )

    # Metadata
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional metadata"
    )


# =============================================================================
# Request/Response Models for API Endpoints
# =============================================================================


class DiscoverFromUrlRequest(BaseModel):
    """Request to discover an external A2A agent from an Agent Card URL."""

    url: str = Field(description="Direct URL to the Agent Card")
    name: Optional[str] = Field(
        default=None, description="Optional display name override"
    )
    custom_headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Headers saved for Agent Card discovery and refresh only",
    )


class DiscoverFromNacosRequest(BaseModel):
    """Request to discover external A2A agents from Nacos."""

    nacos_config_id: str = Field(description="Reference to saved Nacos config")
    agent_names: List[str] = Field(description="List of agent names to discover")
    namespace: str = Field(default="public", description="Nacos namespace")


class ExternalAgentResponse(BaseModel):
    """Response for external agent operations."""

    id: int
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    agent_url: str
    streaming: bool = False
    supported_interfaces: Optional[List[Dict[str, Any]]] = None
    source_type: str
    is_available: bool
    cached_at: Optional[str] = None
    cache_expires_at: Optional[str] = None


class NacosConfigRequest(BaseModel):
    """Request to create a Nacos config."""

    config_id: str = Field(description="Unique config identifier")
    name: str = Field(description="Display name")
    nacos_addr: str = Field(description="Nacos server address")
    nacos_username: Optional[str] = Field(default=None, description="Nacos username")
    nacos_password: Optional[str] = Field(
        default=None, description="Nacos password (encrypted)"
    )
    namespace_id: str = Field(default="public", description="Nacos namespace")
    description: Optional[str] = Field(default=None, description="Description")


class A2AServerSettings(BaseModel):
    """A2A Server settings for an agent."""

    is_enabled: bool = Field(default=False, description="Enable A2A Server")

    # Agent Card fields (extracted from local agent, can be overridden)
    name: Optional[str] = Field(
        default=None, description="Agent name exposed in Agent Card"
    )
    description: Optional[str] = Field(
        default=None, description="Agent description exposed in Agent Card"
    )
    version: Optional[str] = Field(
        default=None, description="Agent version exposed in Agent Card"
    )

    # Primary endpoint URL
    agent_url: Optional[str] = Field(
        default=None, description="Primary A2A endpoint URL"
    )

    # Capabilities
    streaming: bool = Field(
        default=False, description="Whether this agent supports SSE streaming"
    )

    # All supported interfaces (A2A 1.0 compliant)
    supported_interfaces: Optional[List[A2ASupportedInterface]] = Field(
        default=None,
        description="All supported interfaces: [{protocolBinding, url, protocolVersion}, ...]",
    )

    # Agent Card customization (partial overrides)
    card_overrides: Optional[Dict[str, Any]] = Field(
        default=None, description="Agent Card customizations"
    )


class CallExternalAgentRequest(BaseModel):
    """Request to call an external A2A agent."""

    agent_id: int = Field(description="External agent database ID to call")
    message: Dict[str, Any] = Field(description="A2A message payload")
    protocol_binding: Optional[str] = Field(
        default=None,
        description="Specific protocol to use: http-json-rpc, rest, grpc. If not specified, uses default.",
    )
    stream: bool = Field(default=False, description="Enable streaming response")


class TaskListRequest(BaseModel):
    """Request to list A2A tasks."""

    endpoint_id: Optional[str] = Field(default=None, description="Filter by endpoint")
    status: Optional[str] = Field(default=None, description="Filter by status")
    limit: int = Field(default=50, ge=1, le=100, description="Max results")
    offset: int = Field(default=0, ge=0, description="Results offset")


class GatewayA2AServerSettings(BaseModel):
    """A2A Server settings for an agent."""

    model_config = {"extra": "forbid"}

    is_enabled: Annotated[bool | None, Field(strict=True)] = False
    card_overrides: Dict[str, Any] | None = None


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request payload."""

    jsonrpc: str = "2.0"
    method: str
    params: Dict[str, Any] | None = {}
    id: Any | None = None


class DiscoverExternalAgentFromUrlRequest(BaseModel):
    """Request to discover an external A2A agent from an Agent Card URL."""

    url: str
    name: Optional[str] = None
    custom_headers: Optional[Dict[str, str]] = None
    ssl_verify: bool = Field(default=True, description="Verify the peer TLS certificate")


class DiscoverExternalAgentFromNacosRequest(BaseModel):
    """Request to discover external A2A agents from Nacos."""

    nacos_config_id: str
    agent_names: List[str]
    namespace: Optional[str] = "public"


class UpdateAgentProtocolRequest(BaseModel):
    """Request to update the protocol type for an external A2A agent."""

    protocol_type: str = Field(
        description="Protocol type to use: JSONRPC, HTTP+JSON, or GRPC"
    )


class UpdateExternalAgentSecurityCredentialsRequest(BaseModel):
    """Request to configure credentials required by an Agent Card."""

    security_credentials: Dict[str, str] = Field(default_factory=dict)
    selected_security_requirement_index: Optional[int] = Field(default=None, ge=0)


class TestNacosConnectionRequest(BaseModel):
    """Request to test Nacos connectivity without saving the config."""

    nacos_addr: str = Field(
        description="Nacos server address (e.g., http://nacos-server:8848)"
    )
    nacos_username: Optional[str] = None
    nacos_password: Optional[str] = None
    namespace_id: Optional[str] = "public"


class AddRelationRequest(BaseModel):
    """Request body for adding a relation between local agent and external A2A agent."""

    local_agent_id: int
    external_agent_id: int


class CreateNacosConfigRequest(BaseModel):
    """Request to create a Nacos config."""

    name: str
    nacos_addr: str
    nacos_username: Optional[str] = None
    nacos_password: Optional[str] = None
    namespace_id: Optional[str] = "public"
    description: Optional[str] = None


class UpdateNacosConfigRequest(BaseModel):
    """Request to update a Nacos config."""

    name: Optional[str] = None
    nacos_addr: Optional[str] = None
    nacos_username: Optional[str] = None
    nacos_password: Optional[str] = None
    namespace_id: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ChatRequest(BaseModel):
    """Request to send a chat message to an external A2A agent."""

    message: str = Field(..., description="The chat message to send")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional runtime metadata sent as A2A Message.metadata",
    )
    include_metadata: bool = Field(
        default=False,
        description="Deprecated compatibility field. Internal identity is never sent as runtime metadata.",
    )


class ManagementA2AServerSettings(BaseModel):
    """A2A Server settings for an agent."""

    is_enabled: Optional[bool] = False
    card_overrides: Optional[Dict[str, Any]] = None
