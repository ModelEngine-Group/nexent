from enum import Enum
from typing import Optional, Any, List, Dict

from pydantic import BaseModel, Field, EmailStr
from nexent.core.agents.agent_model import ToolConfig


class ModelConnectStatusEnum(Enum):
    """Enum class for model connection status"""
    NOT_DETECTED = "not_detected"
    DETECTING = "detecting"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"

    @classmethod
    def get_default(cls) -> str:
        """Get default value"""
        return cls.NOT_DETECTED.value

    @classmethod
    def get_value(cls, status: Optional[str]) -> str:
        """Get value based on status, return default value if empty"""
        if not status or status == "":
            return cls.NOT_DETECTED.value
        return status


# User authentication related request models
class UserSignUpRequest(BaseModel):
    """User registration request model"""
    email: EmailStr
    password: str = Field(..., min_length=6)
    is_admin: Optional[bool] = False
    invite_code: Optional[str] = None
    with_new_invitation: Optional[bool] = False


class UserSignInRequest(BaseModel):
    """User login request model"""
    email: EmailStr
    password: str


# Response models for model management
class ModelResponse(BaseModel):
    code: int = 200
    message: str = ""
    data: Any


class ModelRequest(BaseModel):
    model_factory: Optional[str] = 'OpenAI-API-Compatible'
    model_name: str
    model_type: str
    api_key: Optional[str] = ''
    base_url: Optional[str] = ''
    max_tokens: Optional[int] = 0
    used_token: Optional[int] = 0
    display_name: Optional[str] = ''
    connect_status: Optional[str] = ''
    expected_chunk_size: Optional[int] = None
    maximum_chunk_size: Optional[int] = None
    chunk_batch: Optional[int] = None


class ProviderModelRequest(BaseModel):
    provider: str
    model_type: str
    api_key: Optional[str] = ''
    base_url: Optional[str] = ''


class BatchCreateModelsRequest(BaseModel):
    api_key: str
    models: List[Dict]
    provider: str
    type: str


# Configuration models
class ModelApiConfig(BaseModel):
    apiKey: str
    modelUrl: str


class SingleModelConfig(BaseModel):
    modelName: str
    displayName: str
    apiConfig: Optional[ModelApiConfig] = None
    dimension: Optional[int] = None


class ModelConfig(BaseModel):
    llm: SingleModelConfig
    embedding: SingleModelConfig
    multiEmbedding: SingleModelConfig
    rerank: SingleModelConfig
    vlm: SingleModelConfig
    stt: SingleModelConfig
    tts: SingleModelConfig


class AppConfig(BaseModel):
    appName: str
    appDescription: str
    iconType: str
    customIconUrl: Optional[str] = None
    avatarUri: Optional[str] = None
    modelEngineEnabled: bool = True


class GlobalConfig(BaseModel):
    app: AppConfig
    models: ModelConfig


# Request models
class AgentRequest(BaseModel):
    query: str
    conversation_id: Optional[int] = None
    is_set: Optional[bool] = False
    history: Optional[List[Dict]] = None
    # Complete list of attachment information
    minio_files: Optional[List[Dict[str, Any]]] = None
    agent_id: Optional[int] = None
    is_debug: Optional[bool] = False


class MessageUnit(BaseModel):
    type: str
    content: str


class MessageRequest(BaseModel):
    conversation_id: int  # Modified to integer type to match database auto-increment ID
    message_idx: int  # Modified to integer type
    role: str
    message: List[MessageUnit]
    # Complete list of attachment information
    minio_files: Optional[List[Dict[str, Any]]] = None


class ConversationRequest(BaseModel):
    title: str = "新对话"


class ConversationResponse(BaseModel):
    code: int = 0  # Modified default value to 0
    message: str = "success"
    data: Any


class RenameRequest(BaseModel):
    conversation_id: int
    name: str


# Pydantic models for API
class TaskRequest(BaseModel):
    source: str
    source_type: str
    chunking_strategy: Optional[str] = None
    index_name: Optional[str] = None
    original_filename: Optional[str] = None
    embedding_model_id: Optional[int] = None
    tenant_id: Optional[str] = None
    additional_params: Dict[str, Any] = Field(default_factory=dict)


class BatchTaskRequest(BaseModel):
    sources: List[Dict[str, Any]
                  ] = Field(..., description="List of source objects to process")


class IndexingResponse(BaseModel):
    success: bool
    message: str
    total_indexed: int
    total_submitted: int


class ChunkCreateRequest(BaseModel):
    """Request payload for manual chunk creation."""

    content: str = Field(..., min_length=1, description="Chunk content")
    title: Optional[str] = Field(None, description="Optional chunk title")
    filename: Optional[str] = Field(None, description="Associated file name")
    path_or_url: Optional[str] = Field(None, description="Source path or URL")
    chunk_id: Optional[str] = Field(
        None, description="Explicit chunk identifier")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional chunk metadata")


class ChunkUpdateRequest(BaseModel):
    """Request payload for chunk updates."""

    content: Optional[str] = Field(None, description="Updated chunk content")
    title: Optional[str] = Field(None, description="Updated chunk title")
    filename: Optional[str] = Field(None, description="Updated file name")
    path_or_url: Optional[str] = Field(
        None, description="Updated source path or URL")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata updates")


class HybridSearchRequest(BaseModel):
    """Request payload for hybrid knowledge-base searches."""
    query: str = Field(..., min_length=1,
                       description="Search query text")
    index_names: List[str] = Field(..., min_items=1,
                                   description="List of index names to search")
    top_k: int = Field(10, ge=1, le=100,
                       description="Number of results to return")
    weight_accurate: float = Field(0.5, ge=0.0, le=1.0,
                                   description="Weight applied to accurate search scores")


# Request models
class ProcessParams(BaseModel):
    chunking_strategy: Optional[str] = "basic"
    source_type: str
    index_name: str
    authorization: Optional[str] = None


class OpinionRequest(BaseModel):
    message_id: int
    opinion: Optional[str] = None


# used in prompt/generate request
class GeneratePromptRequest(BaseModel):
    task_description: str
    agent_id: int
    model_id: int
    tool_ids: Optional[List[int]] = Field(
        None, description="Optional: tool IDs from frontend (takes precedence over database query)")
    sub_agent_ids: Optional[List[int]] = Field(
        None, description="Optional: sub-agent IDs from frontend (takes precedence over database query)")


class GenerateTitleRequest(BaseModel):
    conversation_id: int
    history: List[Dict[str, str]]


# used in agent/search agent/update for save agent info
class AgentInfoRequest(BaseModel):
    agent_id: Optional[int] = None
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    business_description: Optional[str] = None
    author: Optional[str] = None
    model_name: Optional[str] = None
    model_id: Optional[int] = None
    max_steps: Optional[int] = None
    provide_run_summary: Optional[bool] = None
    duty_prompt: Optional[str] = None
    constraint_prompt: Optional[str] = None
    few_shots_prompt: Optional[str] = None
    enabled: Optional[bool] = None
    business_logic_model_name: Optional[str] = None
    business_logic_model_id: Optional[int] = None
    enabled_tool_ids: Optional[List[int]] = None
    related_agent_ids: Optional[List[int]] = None


class AgentIDRequest(BaseModel):
    agent_id: int


class ToolInstanceInfoRequest(BaseModel):
    tool_id: int
    agent_id: int
    params: Dict[str, Any]
    enabled: bool


class ToolInstanceSearchRequest(BaseModel):
    tool_id: int
    agent_id: int


class ToolSourceEnum(Enum):
    LOCAL = "local"
    MCP = "mcp"
    LANGCHAIN = "langchain"


class ToolInfo(BaseModel):
    name: str
    description: str
    params: List
    source: str
    inputs: str
    output_type: str
    class_name: str
    usage: Optional[str]
    origin_name: Optional[str] = None
    category: Optional[str] = None


# used in Knowledge Summary request
class ChangeSummaryRequest(BaseModel):
    summary_result: str


class MessageIdRequest(BaseModel):
    conversation_id: int
    message_index: int


class ExportAndImportAgentInfo(BaseModel):
    agent_id: int
    name: str
    display_name: Optional[str] = None
    description: str
    business_description: str
    author: Optional[str] = None
    max_steps: int
    provide_run_summary: bool
    duty_prompt: Optional[str] = None
    constraint_prompt: Optional[str] = None
    few_shots_prompt: Optional[str] = None
    enabled: bool
    tools: List[ToolConfig]
    managed_agents: List[int]
    model_id: Optional[int] = None
    model_name: Optional[str] = None
    business_logic_model_id: Optional[int] = None
    business_logic_model_name: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True


class MCPInfo(BaseModel):
    mcp_server_name: str
    mcp_url: str


class ExportAndImportDataFormat(BaseModel):
    agent_id: int
    agent_info: Dict[str, ExportAndImportAgentInfo]
    mcp_info: List[MCPInfo]


class AgentImportRequest(BaseModel):
    agent_info: ExportAndImportDataFormat
    force_import: bool = False


class AgentNameBatchRegenerateItem(BaseModel):
    name: str
    display_name: Optional[str] = None
    task_description: Optional[str] = ""
    agent_id: Optional[int] = None


class AgentNameBatchRegenerateRequest(BaseModel):
    items: List[AgentNameBatchRegenerateItem]


class AgentNameBatchCheckItem(BaseModel):
    name: str
    display_name: Optional[str] = None
    agent_id: Optional[int] = None


class AgentNameBatchCheckRequest(BaseModel):
    items: List[AgentNameBatchCheckItem]


class ConvertStateRequest(BaseModel):
    """Request schema for /tasks/convert_state endpoint"""
    process_state: str = ""
    forward_state: str = ""


# ---------------------------------------------------------------------------
# Memory Feature Data Models (Missing previously)
# ---------------------------------------------------------------------------
class MemoryAgentShareMode(str, Enum):
    """Memory sharing mode for agent-level memory.

    always: Agent memories are always shared with others.
    ask:    Ask user every time whether to share.
    never:  Never share agent memories.
    """

    ALWAYS = "always"
    ASK = "ask"
    NEVER = "never"

    @classmethod
    def default(cls) -> "MemoryAgentShareMode":
        return cls.NEVER


# Voice Service Data Models
# ---------------------------------------------------------------------------
class VoiceConnectivityRequest(BaseModel):
    """Request model for voice service connectivity check"""
    model_type: str = Field(...,
                            description="Type of model to check ('stt' or 'tts')")


class VoiceConnectivityResponse(BaseModel):
    """Response model for voice service connectivity check"""
    connected: bool = Field(...,
                            description="Whether the service is connected")
    model_type: str = Field(..., description="Type of model checked")
    message: str = Field(..., description="Status message")


class TTSRequest(BaseModel):
    """Request model for TTS text-to-speech conversion"""
    text: str = Field(..., min_length=1,
                      description="Text to convert to speech")
    stream: bool = Field(True, description="Whether to stream the audio")


class TTSResponse(BaseModel):
    """Response model for TTS conversion"""
    status: str = Field(..., description="Status of the TTS conversion")
    message: Optional[str] = Field(None, description="Additional message")


class ToolValidateRequest(BaseModel):
    """Request model for tool validation"""
    name: str = Field(..., description="Tool name to validate")
    source: str = Field(..., description="Tool source (local, mcp, langchain)")
    usage: Optional[str] = Field(None, description="Tool usage information")
    inputs: Optional[Dict[str, Any]] = Field(
        None, description="Tool inputs")
    params: Optional[Dict[str, Any]] = Field(
        None, description="Tool configuration parameters")


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server"""
    command: str = Field(..., description="Command to run (e.g., 'npx')")
    args: List[str] = Field(default_factory=list,
                            description="Command arguments")
    env: Optional[Dict[str, str]] = Field(
        None, description="Environment variables for the MCP server")
    port: Optional[int] = Field(
        None, description="Host port to expose the MCP server on (e.g., 5020)")
    image: Optional[str] = Field(
        None,
        description="Docker image for the MCP proxy container (optional, overrides MCP_DOCKER_IMAGE)",
    )


class MCPConfigRequest(BaseModel):
    """Request model for adding MCP servers from configuration"""
    mcpServers: Dict[str, MCPServerConfig] = Field(
        ..., description="Dictionary of MCP server configurations")


# Tenant Management Data Models
# ---------------------------------------------------------------------------
class TenantCreateRequest(BaseModel):
    """Request model for creating a tenant"""
    tenant_name: str = Field(..., min_length=1,
                             description="Tenant display name")


class TenantUpdateRequest(BaseModel):
    """Request model for updating tenant information"""
    tenant_name: str = Field(..., min_length=1,
                             description="New tenant display name")


class TenantResponse(BaseModel):
    """Response model for tenant information"""
    tenant_id: str = Field(..., description="Tenant identifier")
    tenant_name: str = Field(..., description="Tenant display name")
    default_group_id: Optional[int] = Field(
        None, description="Default group ID for the tenant")


# Group Management Data Models
# ---------------------------------------------------------------------------
class GroupCreateRequest(BaseModel):
    """Request model for creating a group"""
    tenant_id: str = Field(..., min_length=1,
                           description="Tenant ID where the group belongs")
    group_name: str = Field(..., min_length=1,
                            description="Group display name")
    group_description: Optional[str] = Field(
        None, description="Optional group description")


class GroupUpdateRequest(BaseModel):
    """Request model for updating group information"""
    group_name: Optional[str] = Field(None, description="New group name")
    group_description: Optional[str] = Field(
        None, description="New group description")


class GroupListRequest(BaseModel):
    """Request model for listing groups"""
    tenant_id: str = Field(..., description="Tenant ID to filter groups")
    page: int = Field(1, ge=1, description="Page number for pagination")
    page_size: int = Field(
        20, ge=1, le=100, description="Number of items per page")


class GroupUserRequest(BaseModel):
    """Request model for adding/removing user from group"""
    user_id: str = Field(..., min_length=1,
                         description="User ID to add/remove")
    group_ids: Optional[List[int]] = Field(
        None, description="List of group IDs (for batch operations)")


class SetDefaultGroupRequest(BaseModel):
    """Request model for setting tenant's default group"""
    default_group_id: int = Field(..., ge=1,
                                  description="Group ID to set as default for the tenant")


# Invitation Management Data Models
# ---------------------------------------------------------------------------
class InvitationCreateRequest(BaseModel):
    """Request model for creating invitation code"""
    code_type: str = Field(
        ..., description="Invitation code type (ADMIN_INVITE, DEV_INVITE, USER_INVITE)")
    invitation_code: Optional[str] = Field(
        None, description="Custom invitation code (auto-generated if not provided)")
    group_ids: Optional[List[int]] = Field(
        None, description="Associated group IDs")
    capacity: int = Field(
        default=1, ge=1, description="Maximum usage capacity")
    expiry_date: Optional[str] = Field(
        None, description="Expiry date in ISO format")


class InvitationUpdateRequest(BaseModel):
    """Request model for updating invitation code"""
    capacity: Optional[int] = Field(None, ge=1, description="New capacity")
    expiry_date: Optional[str] = Field(None, description="New expiry date")
    group_ids: Optional[List[int]] = Field(None, description="New group IDs")


class InvitationResponse(BaseModel):
    """Response model for invitation information"""
    invitation_id: int = Field(..., description="Invitation ID")
    invitation_code: str = Field(..., description="Invitation code")
    code_type: str = Field(..., description="Code type")
    group_ids: Optional[List[int]] = Field(
        None, description="Associated group IDs")
    capacity: int = Field(..., description="Usage capacity")
    expiry_date: Optional[str] = Field(None, description="Expiry date")
    status: str = Field(..., description="Current status")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(
        None, description="Last update timestamp")


class InvitationListRequest(BaseModel):
    """Request model for listing invitation codes"""
    tenant_id: Optional[str] = Field(
        None, description="Tenant ID to filter by (optional)")
    page: int = Field(1, ge=1, description="Page number for pagination")
    page_size: int = Field(
        20, ge=1, le=100, description="Number of items per page")


class InvitationUseResponse(BaseModel):
    """Response model for invitation usage"""
    invitation_record_id: int = Field(..., description="Usage record ID")
    invitation_code: str = Field(..., description="Used invitation code")
    user_id: str = Field(..., description="User who used the code")
    invitation_id: int = Field(..., description="Invitation ID")
    code_type: str = Field(..., description="Code type")
    group_ids: Optional[List[int]] = Field(
        None, description="Associated group IDs")
