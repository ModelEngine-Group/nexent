from enum import Enum
from typing import Optional, Any, List, Dict

from pydantic import BaseModel, Field

from nexent.core.agents.agent_model import ToolConfig


class ModelConnectStatusEnum(Enum):
    """Enum class for model connection status"""
    NOT_DETECTED = "未检测"
    DETECTING = "检测中"
    AVAILABLE = "可用"
    UNAVAILABLE = "不可用"

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


class FileInfo(BaseModel):
    path_or_url: str = Field(..., description="Document source path or URL")
    file: str = Field(..., description="File name or identifier")
    file_size: Optional[int] = Field(None, description="Size of the file in bytes")
    create_time: Optional[str] = Field(None, description="Creation time of the file")


class IndexInfo(BaseModel):
    base_info: Dict[str, Any]
    search_performance: Dict[str, Any]
    fields: List[str]
    doc_count: int
    chunk_count: int
    process_source: str
    embedding_model: Optional[str] = Field(None, description="Embedding model used")
    files: Optional[List[FileInfo]] = Field(None, description="List of files in the index")


class IndexingResponse(BaseModel):
    success: bool
    message: str
    total_indexed: int
    total_submitted: int


class DocumentResponse(BaseModel):
    id: str
    title: str
    filename: str
    path_or_url: str
    language: Optional[str] = None
    author: Optional[str] = None
    date: Optional[str] = None
    content: str
    process_source: str
    embedding_model_name: Optional[str] = None
    file_size: Optional[int] = None
    create_time: Optional[str] = None
    score: Optional[float] = None

# Request models
class ProcessParams(BaseModel):
    chunking_strategy: Optional[str] = "basic"
    source_type: str
    index_name: str


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
    description: Optional[str] = None
    business_description: Optional[str] = None
    model_name: Optional[str] = None
    max_steps: Optional[int] = None
    provide_run_summary: Optional[bool] = None
    prompt: Optional[str] = None
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
    name: str
    description: str
    business_description: str
    model_name: str
    max_steps: int
    provide_run_summary: bool
    prompt: str
    enabled: bool
    tools: List[ToolConfig]
    managed_agents: List


class AgentImportRequest(BaseModel):
    agent_id: int
    agent_info: ExportAndImportAgentInfo
