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

# Request models for user authentication
STATUS_CODES = {
    "SUCCESS": 200,
    # 客户端错误状态码
    "USER_EXISTS": 1001,
    "INVALID_CREDENTIALS": 1002,
    "TOKEN_EXPIRED": 1003,
    "UNAUTHORIZED": 1004,
    "SERVER_ERROR": 1005,
    "INVALID_INPUT": 1006,
    "AUTH_SERVICE_UNAVAILABLE": 1007,
}

# 用户认证相关请求模型
class UserSignUpRequest(BaseModel):
    """User registration request model"""
    email: EmailStr
    password: str = Field(..., min_length=6)
    is_admin: Optional[bool] = False
    invite_code: Optional[str] = None

class UserSignInRequest(BaseModel):
    """User login request model"""
    email: EmailStr
    password: str

class UserUpdateRequest(BaseModel):
    """User information update request model"""
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6)
    role: Optional[str] = None


# Response models for user management
class ServiceResponse(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


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


class ProviderModelRequest(BaseModel):
    provider: str
    model_type: str
    api_key: Optional[str] = ''


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
    llmSecondary: SingleModelConfig
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


class GlobalConfig(BaseModel):
    app: AppConfig
    models: ModelConfig


# Request models
class AgentRequest(BaseModel):
    query: str
    conversation_id: Optional[int] = None
    is_set: Optional[bool] = False
    history: Optional[List[Dict]] = None
    minio_files: Optional[List[Dict[str, Any]]] = None  # Complete list of attachment information
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
    minio_files: Optional[List[Dict[str, Any]]] = None  # Complete list of attachment information


class ConversationRequest(BaseModel):
    title: str = "新对话"


class ConversationResponse(BaseModel):
    code: int = 0  # Modified default value to 0
    message: str = "success"
    data: Any


class RenameRequest(BaseModel):
    conversation_id: int
    name: str


class GenerateTitleRequest(BaseModel):
    conversation_id: int
    history: List[Dict[str, str]]


# Pydantic models for API
class TaskRequest(BaseModel):
    source: str
    source_type: str
    chunking_strategy: Optional[str] = None
    index_name: Optional[str] = None
    original_filename: Optional[str] = None
    additional_params: Dict[str, Any] = Field(default_factory=dict)



class BatchTaskRequest(BaseModel):
    sources: List[Dict[str, Any]] = Field(..., description="List of source objects to process")


class TaskResponse(BaseModel):
    task_id: str


class BatchTaskResponse(BaseModel):
    task_ids: List[str]


class SimpleTaskStatusResponse(BaseModel):
    id: str
    task_name: str
    index_name: str
    path_or_url: str
    original_filename: str
    status: str
    created_at: float
    updated_at: float
    error: Optional[str] = None


class SimpleTasksListResponse(BaseModel):
    tasks: List[SimpleTaskStatusResponse]


class IndexingResponse(BaseModel):
    success: bool
    message: str
    total_indexed: int
    total_submitted: int


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


class GenerateTitleRequest(BaseModel):
    conversation_id: int
    history: List[Dict[str, str]]


# used in prompt/finetune request
class FineTunePromptRequest(BaseModel):
    agent_id: int
    system_prompt: str
    command: str

# used in agent/search agent/update for save agent info
class AgentInfoRequest(BaseModel):
    agent_id: int
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    business_description: Optional[str] = None
    model_name: Optional[str] = None
    max_steps: Optional[int] = None
    provide_run_summary: Optional[bool] = None
    duty_prompt: Optional[str] = None
    constraint_prompt: Optional[str] = None
    few_shots_prompt: Optional[str] = None
    enabled: Optional[bool] = None


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
    model_name: str
    max_steps: int
    provide_run_summary: bool
    duty_prompt: Optional[str] = None
    constraint_prompt: Optional[str] = None
    few_shots_prompt: Optional[str] = None
    enabled: bool
    tools: List[ToolConfig]
    managed_agents: List[int]

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


class ConvertStateRequest(BaseModel):
    """Request schema for /tasks/convert_state endpoint"""
    process_state: str = ""
    forward_state: str = ""


class ConvertStateResponse(BaseModel):
    """Response schema for /tasks/convert_state endpoint"""
    state: str


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