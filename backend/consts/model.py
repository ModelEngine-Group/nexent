from enum import Enum
from typing import Annotated, Optional, Any, List, Dict, Literal, Union
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)
from nexent.core.agents.agent_model import AgentVerificationConfig, ToolConfig

from consts.prompt_template import PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP


def _validated_context_policy(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Validate a partial request/agent policy while preserving its layer shape."""
    if value is None:
        return None
    from nexent.core.agents.context import PolicyLayers, resolve_policy

    resolve_policy(PolicyLayers(request=value))
    return value


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
    password: str = Field(..., min_length=8)
    invite_code: Optional[str] = None
    auto_login: Optional[bool] = True  # Whether to return session after signup


class UserSignInRequest(BaseModel):
    """User login request model"""

    email: EmailStr
    password: str


class OAuthCompleteRequest(BaseModel):
    """Complete a pending OAuth signup."""

    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=6)
    invite_code: str = Field(..., min_length=1)


class UpdatePasswordRequest(BaseModel):
    """Password update request model for changing user password"""

    old_password: str = Field(..., min_length=1, description="Current password for verification")
    new_password: str = Field(..., min_length=8, description="New password to set (min 8 characters)")


class UserUpdateRequest(BaseModel):
    """User update request model"""

    username: Optional[str] = Field(None, min_length=1, max_length=50)
    email: Optional[EmailStr] = None
    role: Optional[str] = Field(None, pattern="^(SUPER_ADMIN|ADMIN|DEV|USER)$")


class UserDeleteRequest(BaseModel):
    """User delete request model"""

    new_owner_id: Optional[str] = None


class OAuthProviderDefinition(BaseModel):
    name: str
    display_name: str
    icon: str

    authorize_url: str
    authorize_method: str = "GET"
    authorize_params: Dict[str, str] = {}
    authorize_fragment: str = ""
    authorize_param_map: Dict[str, str] = {
        "client_id": "client_id",
        "redirect_uri": "redirect_uri",
        "scope": "scope",
        "state": "state",
    }
    encode_redirect_uri: bool = False

    token_url: str
    token_method: str = "POST"
    token_params_map: Dict[str, str] = {
        "client_id": "client_id",
        "client_secret": "client_secret",
        "code": "code",
        "grant_type": "grant_type",
    }
    token_extra_params: Dict[str, str] = {}
    token_error_key: Optional[str] = None
    token_error_message_key: Optional[str] = None
    token_response_id_key: Optional[str] = None

    userinfo_url: str
    userinfo_auth_scheme: str = "Bearer"
    userinfo_params: Dict[str, str] = {}
    userinfo_field_map: Dict[str, str] = {
        "id": "id",
        "email": "email",
        "username": "login",
    }
    userinfo_needs_email_fetch: bool = False
    userinfo_email_url: Optional[str] = None

    client_id_env: str
    client_secret_env: str
    enabled_check: Optional[str] = None


# Response models for model management
class ModelResponse(BaseModel):
    code: int = 200
    message: str = ""
    data: Any


class ModelRequest(BaseModel):
    model_factory: Optional[str] = "OpenAI-API-Compatible"
    model_name: str
    model_type: str
    api_key: Optional[str] = ""
    base_url: Optional[str] = ""
    max_tokens: Optional[int] = 0
    used_token: Optional[int] = 0
    display_name: Optional[str] = ""
    connect_status: Optional[str] = ""
    expected_chunk_size: Optional[int] = None
    maximum_chunk_size: Optional[int] = None
    chunk_batch: Optional[int] = None
    # STT specific fields
    model_appid: Optional[str] = None
    access_token: Optional[str] = None
    timeout_seconds: Optional[int] = None
    concurrency_limit: Optional[int] = None
    # W1 capacity fields (see W1 ADR). All nullable; resolver applies precedence.
    context_window_tokens: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    default_output_reserve_tokens: Optional[int] = None
    tokenizer_family: Optional[str] = None
    capacity_source: Optional[str] = None
    capability_profile_version: Optional[str] = None
    # W11 accept-signal fields (audit/metrics only — never persisted). Sent by
    # the frontend when the operator clicks "Use suggestion" and saves; the
    # app layer pops them before the dict reaches the service/DB layer and
    # forwards them to model_capacity_suggestion_accept_total.
    accepted_suggestion_match_kind: Optional[str] = None
    accepted_capability_profile_version: Optional[str] = None


class CapacitySuggestionFields(BaseModel):
    context_window_tokens: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    default_output_reserve_tokens: Optional[int] = None
    tokenizer_family: Optional[str] = None


class ModelCapacitySuggestionRequest(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=512)
    base_url: Optional[str] = None
    provider_hint: Optional[str] = None
    api_key: Optional[str] = None
    model_type: Optional[str] = None


class ModelCapacitySuggestionResponse(BaseModel):
    suggestions: Optional[CapacitySuggestionFields] = None
    match_kind: Literal["catalog_exact", "catalog_fuzzy", "provider_discovery", "none"]
    match_confidence: Optional[Literal["high", "medium", "low"]] = None
    match_explanation: str
    suggested_provider: Optional[str] = None
    canonical_model_name: Optional[str] = None
    capability_profile_version: Optional[str] = None
    capacity_source_on_accept: Optional[Literal["operator"]] = None


class CapacityCoverageBareModel(BaseModel):
    model_id: int
    model_name: str
    model_factory: Optional[str] = None
    model_type: Literal["llm", "vlm", "vlm2", "vlm3"]
    max_tokens: Optional[int] = None
    suggestion_available: bool = False


class CapacityCoverageResponse(BaseModel):
    total_llm_vlm: int
    bare_count: int
    bare_models: List[CapacityCoverageBareModel] = Field(default_factory=list)


class ProviderModelRequest(BaseModel):
    provider: str
    model_type: str
    api_key: Optional[str] = ""
    base_url: Optional[str] = ""


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


class STTModelConfig(BaseModel):
    """STT model specific configuration with factory, appid, and access token fields"""

    modelName: str
    displayName: str
    apiConfig: Optional[ModelApiConfig] = None
    modelFactory: Optional[str] = None
    modelAppid: Optional[str] = None
    accessToken: Optional[str] = None


def _empty_model_config() -> SingleModelConfig:
    return SingleModelConfig(modelName="", displayName="", apiConfig=ModelApiConfig(apiKey="", modelUrl=""))


class TTSModelConfig(BaseModel):
    """TTS model specific configuration with factory, appid, and access token fields"""

    modelName: str
    displayName: str
    apiConfig: Optional[ModelApiConfig] = None
    modelFactory: Optional[str] = None
    modelAppid: Optional[str] = None
    accessToken: Optional[str] = None


class ModelConfig(BaseModel):
    llm: SingleModelConfig
    embedding: SingleModelConfig
    multiEmbedding: SingleModelConfig
    rerank: SingleModelConfig
    vlm: SingleModelConfig
    vlm2: SingleModelConfig = Field(default_factory=_empty_model_config)
    vlm3: SingleModelConfig = Field(default_factory=_empty_model_config)
    stt: STTModelConfig
    tts: TTSModelConfig


class AppConfig(BaseModel):
    appName: str
    appDescription: str
    iconType: str
    iconKey: Optional[str] = "search"
    customIconUrl: Optional[str] = None
    avatarUri: Optional[str] = None
    modelEngineEnabled: bool = False
    datamateUrl: Optional[str] = None


class GlobalConfig(BaseModel):
    app: AppConfig
    models: ModelConfig


# Request models
class HistoryItem(BaseModel):
    role: str
    content: str
    minio_files: Optional[List[Dict[str, Any]]] = None


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


Nl2AgentActionType = Literal[
    "confirm_requirements",
    "save_model_selection",
    "apply_local_resources",
    "skip_local_resources",
    "install_mcp",
    "bind_mcp_tools",
    "skip_mcp_tools",
    "install_web_skill",
    "complete_online_configuration",
    "save_identity",
    "finalize",
]


class Nl2AgentActionContext(BaseModel):
    """A server-validated action reference used for the next NL2AGENT turn."""

    model_config = ConfigDict(extra="forbid")

    action_id: UUID
    action: Nl2AgentActionType
    display_text: str = Field(min_length=1, max_length=500)
    workflow_revision: int = Field(strict=True, ge=0)


class AgentRequest(BaseModel):
    query: str
    conversation_id: Optional[int] = None
    history: Optional[List[HistoryItem]] = None
    # Complete list of attachment information
    minio_files: Optional[List[Dict[str, Any]]] = None
    agent_id: Optional[int] = None
    # Target draft agent being built by NL2AGENT. When set, NL2AGENT builtin
    # tools operate on this draft instead of the running NL2AGENT agent.
    draft_agent_id: Optional[int] = None
    nl2agent_action_context: Optional[Nl2AgentActionContext] = None
    model_id: Optional[int] = None
    requested_output_tokens: Optional[int] = Field(default=None, gt=0)
    version_no: Optional[int] = None
    is_debug: Optional[bool] = False
    tool_params: Optional[ToolParamsRequest] = None
    context_policy: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional request-scoped context policy override",
    )

    @field_validator("context_policy")
    @classmethod
    def validate_context_policy(cls, value):
        return _validated_context_policy(value)
    enable_plan: Optional[bool] = Field(
        default=False,
        description="Whether to enable the planning phase before execution"
    )

    @model_validator(mode="after")
    def validate_nl2agent_action_context(self):
        """Keep structured actions bound to one attachment-free NL2AGENT turn."""
        action = self.nl2agent_action_context
        if action is None:
            return self
        if (
            not isinstance(self.draft_agent_id, int)
            or isinstance(self.draft_agent_id, bool)
            or self.draft_agent_id <= 0
        ):
            raise ValueError("nl2agent_action_context requires a valid draft_agent_id")
        if self.minio_files:
            raise ValueError("nl2agent_action_context does not accept attachments")
        if self.query.strip() != action.display_text.strip():
            raise ValueError("query must match nl2agent_action_context.display_text")
        return self


class MessageUnit(BaseModel):
    type: str
    content: str


class MessageRequest(BaseModel):
    conversation_id: int  # Modified to integer type to match database auto-increment ID
    message_idx: int  # Modified to integer type
    role: str
    message: List[MessageUnit]
    message_type: str = "chat"
    message_metadata: Dict[str, Any] = Field(default_factory=dict)
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
    sources: List[Dict[str, Any]] = Field(..., description="List of source objects to process")


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
    chunk_id: Optional[str] = Field(None, description="Explicit chunk identifier")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional chunk metadata")


class ChunkUpdateRequest(BaseModel):
    """Request payload for chunk updates."""

    content: Optional[str] = Field(None, description="Updated chunk content")
    title: Optional[str] = Field(None, description="Updated chunk title")
    filename: Optional[str] = Field(None, description="Updated file name")
    path_or_url: Optional[str] = Field(None, description="Updated source path or URL")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata updates")


class HybridSearchRequest(BaseModel):
    """Request payload for hybrid knowledge-base searches."""

    query: str = Field(..., min_length=1, description="Search query text")
    index_names: List[str] = Field(..., min_items=1, description="List of index names to search")
    top_k: int = Field(10, ge=1, le=100, description="Number of results to return")
    weight_accurate: float = Field(0.5, ge=0.0, le=1.0, description="Weight applied to accurate search scores")


# Request models
class ProcessParams(BaseModel):
    chunking_strategy: Optional[str] = "basic"
    source_type: str
    index_name: str
    authorization: Optional[str] = None
    model_id: Optional[int] = None


class OpinionRequest(BaseModel):
    message_id: int
    opinion: Optional[str] = None


# used in prompt/generate request
class GeneratePromptRequest(BaseModel):
    task_description: str
    agent_id: int
    model_id: int
    prompt_template_id: Optional[int] = None
    tool_ids: Optional[List[int]] = Field(
        None,
        description="Optional: tool IDs from frontend (takes precedence over database query)",
    )
    sub_agent_ids: Optional[List[int]] = Field(
        None,
        description="Optional: sub-agent IDs from frontend (takes precedence over database query)",
    )
    knowledge_base_display_names: Optional[List[str]] = Field(
        None,
        description="Optional: knowledge base display names from frontend (takes precedence over database query)",
    )
    has_selected_resources: bool = Field(
        True,
        description="Whether tools or sub-agents are selected; when False, skips generating constraint and few_shots sections",
    )


class _StrictNl2AgentRequest(BaseModel):
    """Reject undeclared fields at every NL2AGENT HTTP boundary."""

    model_config = ConfigDict(extra="forbid")


Nl2AgentPositiveInt = Annotated[int, Field(strict=True, ge=1)]
Nl2AgentItemKey = Annotated[str, Field(min_length=1, max_length=300)]


def _parse_nl2agent_json_object_id(value: Any) -> Any:
    """Normalize one canonical JSON object key before strict ID validation."""
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        return value
    if len(value) > 1 and value.startswith("0"):
        return value
    try:
        return int(value)
    except ValueError:
        return value


Nl2AgentJsonPositiveIntKey = Annotated[
    int,
    BeforeValidator(_parse_nl2agent_json_object_id),
    Field(strict=True, ge=1),
]


class Nl2AgentRequirementsSummaryPayload(_StrictNl2AgentRequest):
    """The five-field requirements summary visible in a confirmation card."""

    goal: str = Field(..., min_length=1, max_length=500)
    audience_or_scenario: str = Field(..., min_length=1, max_length=500)
    primary_input: str = Field(..., min_length=1, max_length=1000)
    expected_output: str = Field(..., min_length=1, max_length=1000)
    key_constraints: str = Field(..., min_length=1, max_length=2000)


class Nl2AgentConfirmRequirementsActionPayload(_StrictNl2AgentRequest):
    summary: Nl2AgentRequirementsSummaryPayload


class Nl2AgentSaveModelSelectionActionPayload(_StrictNl2AgentRequest):
    primary_model_id: Nl2AgentPositiveInt
    fallback_model_ids: List[Nl2AgentPositiveInt] = Field(
        default_factory=list, max_length=4
    )


class Nl2AgentApplyLocalResourcesActionPayload(_StrictNl2AgentRequest):
    """Select resources only from one server-recorded recommendation batch."""

    recommendation_batch_id: str = Field(..., min_length=1, max_length=128)
    tool_ids: List[Nl2AgentPositiveInt] = Field(default_factory=list, max_length=100)
    skill_ids: List[Nl2AgentPositiveInt] = Field(default_factory=list, max_length=100)
    tool_config_values: Dict[Nl2AgentJsonPositiveIntKey, Dict[str, Any]] = Field(
        default_factory=dict, max_length=100
    )


class Nl2AgentSkipLocalResourcesActionPayload(_StrictNl2AgentRequest):
    """Skip one server-recorded local recommendation batch."""

    recommendation_batch_id: str = Field(..., min_length=1, max_length=128)


class Nl2AgentInstallMcpActionPayload(_StrictNl2AgentRequest):
    """Install one MCP recommendation without accepting a client URL."""

    recommendation_batch_id: str = Field(..., min_length=1, max_length=128)
    recommendation_id: Nl2AgentItemKey
    option_id: str = Field(default="remote", min_length=1, max_length=100)
    config_values: Dict[str, Any] = Field(default_factory=dict, max_length=100)


class Nl2AgentBindMcpToolsActionPayload(_StrictNl2AgentRequest):
    recommendation_id: Nl2AgentItemKey
    tool_ids: List[Nl2AgentPositiveInt] = Field(default_factory=list, max_length=100)


class Nl2AgentSkipMcpToolsActionPayload(_StrictNl2AgentRequest):
    recommendation_id: Nl2AgentItemKey


class Nl2AgentInstallWebSkillActionPayload(_StrictNl2AgentRequest):
    """Install one Skill from a server-recorded recommendation batch."""

    recommendation_batch_id: str = Field(..., min_length=1, max_length=128)
    item_key: Nl2AgentItemKey
    config_values: Dict[str, Any] = Field(default_factory=dict, max_length=100)


class Nl2AgentEmptyActionPayload(_StrictNl2AgentRequest):
    """An action with no client-controlled domain identifiers."""


class Nl2AgentSaveIdentityActionPayload(_StrictNl2AgentRequest):
    display_name: str = Field(..., min_length=1, max_length=50)

class Nl2AgentFinalizeActionPayload(_StrictNl2AgentRequest):
    """Unsaved descriptive, prompt, and runtime fields for draft publication."""

    description: Optional[str] = Field(default=None, max_length=500)

    # Task
    business_description: str = Field(..., min_length=1, max_length=2000)

    # Prompts
    duty_prompt: str = Field(..., min_length=1, max_length=8000)
    constraint_prompt: Optional[str] = Field(default=None, max_length=4000)
    few_shots_prompt: Optional[str] = Field(default=None, max_length=8000)

    # UI
    greeting_message: str = Field(..., min_length=1, max_length=500)
    example_questions: List[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=6
    )

    # Runtime
    max_steps: Optional[Annotated[int, Field(strict=True, ge=1, le=30)]] = None
    requested_output_tokens: Optional[Nl2AgentPositiveInt] = None
    provide_run_summary: bool = Field(default=False)
    verification_config: Optional[Dict[str, Any]] = Field(default=None)

    @field_validator("verification_config", mode="before")
    @classmethod
    def normalize_nl2agent_verification_config(cls, value):
        if value is None:
            return None
        return AgentVerificationConfig.model_validate(value).model_dump()
    enable_context_manager: bool = Field(default=True)


class _Nl2AgentActionRequestBase(_StrictNl2AgentRequest):
    action_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    display_text: str = Field(..., min_length=1, max_length=500)


class Nl2AgentConfirmRequirementsActionRequest(_Nl2AgentActionRequestBase):
    action: Literal["confirm_requirements"]
    payload: Nl2AgentConfirmRequirementsActionPayload


class Nl2AgentSaveModelSelectionActionRequest(_Nl2AgentActionRequestBase):
    action: Literal["save_model_selection"]
    payload: Nl2AgentSaveModelSelectionActionPayload


class Nl2AgentApplyLocalResourcesActionRequest(_Nl2AgentActionRequestBase):
    action: Literal["apply_local_resources"]
    payload: Nl2AgentApplyLocalResourcesActionPayload


class Nl2AgentSkipLocalResourcesActionRequest(_Nl2AgentActionRequestBase):
    action: Literal["skip_local_resources"]
    payload: Nl2AgentSkipLocalResourcesActionPayload


class Nl2AgentInstallMcpActionRequest(_Nl2AgentActionRequestBase):
    action: Literal["install_mcp"]
    payload: Nl2AgentInstallMcpActionPayload


class Nl2AgentBindMcpToolsActionRequest(_Nl2AgentActionRequestBase):
    action: Literal["bind_mcp_tools"]
    payload: Nl2AgentBindMcpToolsActionPayload


class Nl2AgentSkipMcpToolsActionRequest(_Nl2AgentActionRequestBase):
    action: Literal["skip_mcp_tools"]
    payload: Nl2AgentSkipMcpToolsActionPayload


class Nl2AgentInstallWebSkillActionRequest(_Nl2AgentActionRequestBase):
    action: Literal["install_web_skill"]
    payload: Nl2AgentInstallWebSkillActionPayload


class Nl2AgentCompleteOnlineConfigurationActionRequest(_Nl2AgentActionRequestBase):
    action: Literal["complete_online_configuration"]
    payload: Nl2AgentEmptyActionPayload = Field(default_factory=Nl2AgentEmptyActionPayload)


class Nl2AgentSaveIdentityActionRequest(_Nl2AgentActionRequestBase):
    action: Literal["save_identity"]
    payload: Nl2AgentSaveIdentityActionPayload


class Nl2AgentFinalizeActionRequest(_Nl2AgentActionRequestBase):
    action: Literal["finalize"]
    payload: Nl2AgentFinalizeActionPayload


Nl2AgentActionRequest = Annotated[
    Union[
        Nl2AgentConfirmRequirementsActionRequest,
        Nl2AgentSaveModelSelectionActionRequest,
        Nl2AgentApplyLocalResourcesActionRequest,
        Nl2AgentSkipLocalResourcesActionRequest,
        Nl2AgentInstallMcpActionRequest,
        Nl2AgentBindMcpToolsActionRequest,
        Nl2AgentSkipMcpToolsActionRequest,
        Nl2AgentInstallWebSkillActionRequest,
        Nl2AgentCompleteOnlineConfigurationActionRequest,
        Nl2AgentSaveIdentityActionRequest,
        Nl2AgentFinalizeActionRequest,
    ],
    Field(discriminator="action"),
]


class Nl2AgentActionResponse(_StrictNl2AgentRequest):
    action_id: UUID
    action: Nl2AgentActionType
    status: Literal["applied", "pending", "replayed"]
    workflow_revision: int = Field(ge=0)
    result: Dict[str, Any] = Field(default_factory=dict)


class PromptTemplateContentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    duty_system_prompt: str = Field(alias=PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP["duty_system_prompt"])
    constraint_system_prompt: str = Field(alias=PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP["constraint_system_prompt"])
    few_shots_system_prompt: str = Field(alias=PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP["few_shots_system_prompt"])
    agent_variable_name_system_prompt: str = Field(
        alias=PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP["agent_variable_name_system_prompt"]
    )
    agent_display_name_system_prompt: str = Field(
        alias=PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP["agent_display_name_system_prompt"]
    )
    agent_description_system_prompt: str = Field(
        alias=PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP["agent_description_system_prompt"]
    )
    user_prompt: str = Field(alias=PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP["user_prompt"])
    agent_name_regenerate_system_prompt: str = Field(
        alias=PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP["agent_name_regenerate_system_prompt"]
    )
    agent_name_regenerate_user_prompt: str = Field(
        alias=PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP["agent_name_regenerate_user_prompt"]
    )
    agent_display_name_regenerate_system_prompt: str = Field(
        alias=PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP["agent_display_name_regenerate_system_prompt"]
    )
    agent_display_name_regenerate_user_prompt: str = Field(
        alias=PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP["agent_display_name_regenerate_user_prompt"]
    )


class PromptTemplateRequest(BaseModel):
    template_name: str
    description: Optional[str] = None
    template_type: str = "agent_generate"
    template_content_zh: PromptTemplateContentRequest
    template_content_en: Optional[PromptTemplateContentRequest] = None


class OptimizePromptSectionRequest(BaseModel):
    task_description: str
    agent_id: int
    model_id: int
    section_type: str
    section_title: str
    current_content: str
    feedback: str
    mode: Literal["general", "insert", "select"] = "general"
    start_pos: Optional[int] = Field(None, description="Start position for insert/select mode")
    end_pos: Optional[int] = Field(None, description="End position for insert/select mode")
    tool_ids: Optional[List[int]] = Field(
        None,
        description="Optional: tool IDs from frontend (takes precedence over database query)",
    )
    sub_agent_ids: Optional[List[int]] = Field(
        None,
        description="Optional: sub-agent IDs from frontend (takes precedence over database query)",
    )
    knowledge_base_display_names: Optional[List[str]] = Field(
        None,
        description="Optional: knowledge base display names from frontend (takes precedence over database query)",
    )


class BadCaseItem(BaseModel):
    question: str
    answer: str
    label: Optional[str] = None
    reason: Optional[str] = None


class OptimizePromptBadCaseRequest(BaseModel):
    agent_id: int
    model_id: int
    current_content: str
    bad_cases: List[BadCaseItem]
    section_type: str
    section_title: str
    tool_ids: Optional[List[int]] = Field(None)
    sub_agent_ids: Optional[List[int]] = Field(None)
    knowledge_base_display_names: Optional[List[str]] = Field(None)


class OptimizeFromDebugSelected(BaseModel):
    user_question: str
    assistant_answer: str


class OptimizePromptFromDebugRequest(BaseModel):
    agent_id: int
    model_id: int
    feedback: str
    selected: OptimizeFromDebugSelected
    history: Optional[List[HistoryItem]] = None


class GenerateTitleRequest(BaseModel):
    conversation_id: int
    question: str


# used in agent/search agent/update for save agent info
class AgentInfoRequest(BaseModel):
    agent_id: Optional[int] = None
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    business_description: Optional[str] = None
    author: Optional[str] = None
    model_ids: Optional[List[int]] = None
    max_steps: Optional[int] = Field(default=None, ge=1)
    requested_output_tokens: Optional[int] = Field(default=None, gt=0)
    is_main_agent: Optional[bool] = None
    provide_run_summary: Optional[bool] = None
    duty_prompt: Optional[str] = None
    constraint_prompt: Optional[str] = None
    few_shots_prompt: Optional[str] = None
    enabled: Optional[bool] = None
    business_logic_model_name: Optional[str] = None
    business_logic_model_id: Optional[int] = None
    prompt_template_id: Optional[int] = None
    prompt_template_name: Optional[str] = None
    enabled_tool_ids: Optional[List[int]] = None
    enabled_skill_ids: Optional[List[int]] = None
    related_agent_ids: Optional[List[int]] = None
    related_external_agent_ids: Optional[List[int]] = None
    group_ids: Optional[List[int]] = None
    ingroup_permission: Optional[str] = None
    enable_context_manager: Optional[bool] = None
    verification_config: Optional[Dict[str, Any]] = None
    context_policy: Optional[Dict[str, Any]] = None

    greeting_message: Optional[str] = None
    example_questions: Optional[List[str]] = None
    version_no: int = 0

    @field_validator("verification_config", mode="before")
    @classmethod
    def normalize_verification_config(cls, value):
        if value is None:
            return None
        return AgentVerificationConfig.model_validate(value).model_dump()

    @field_validator("context_policy")
    @classmethod
    def validate_context_policy(cls, value):
        return _validated_context_policy(value)


class AgentIDRequest(BaseModel):
    agent_id: int


class ToolInstanceInfoRequest(BaseModel):
    tool_id: int
    agent_id: int
    params: Dict[str, Any]
    enabled: bool
    version_no: int = 0


class SkillInstanceInfoRequest(BaseModel):
    """Request model for skill instance update.

    Note: skill_description and skill_content are no longer accepted.
    These fields are now retrieved from ag_skill_info_t table.
    """

    skill_id: int
    agent_id: int
    enabled: bool = True
    version_no: int = 0
    config_values: Optional[Dict[str, Any]] = None


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


# used in Knowledge Summary request
class ChangeSummaryRequest(BaseModel):
    summary_result: str


class MessageIdRequest(BaseModel):
    conversation_id: int
    message_index: int


class ExportAndImportAgentInfo(BaseModel):
    agent_id: int
    tenant_id: Optional[str] = None
    name: str
    display_name: Optional[str] = None
    description: str
    business_description: str
    author: Optional[str] = None
    max_steps: int
    requested_output_tokens: Optional[int] = Field(default=None, gt=0)
    is_main_agent: bool = True
    provide_run_summary: bool
    verification_config: Optional[Dict[str, Any]] = None
    context_policy: Optional[Dict[str, Any]] = None
    duty_prompt: Optional[str] = None
    constraint_prompt: Optional[str] = None
    few_shots_prompt: Optional[str] = None
    enabled: bool
    tools: List[ToolConfig]
    managed_agents: List[int]
    model_ids: Optional[List[int]] = None
    model_names: Optional[List[str]] = None
    business_logic_model_id: Optional[int] = None
    business_logic_model_name: Optional[str] = None
    skill_names: Optional[List[str]] = None
    prompt_template_id: Optional[int] = None
    prompt_template_name: Optional[str] = None

    @field_validator("context_policy")
    @classmethod
    def validate_context_policy(cls, value):
        return _validated_context_policy(value)

    class Config:
        arbitrary_types_allowed = True


class MCPInfo(BaseModel):
    mcp_server_name: str
    mcp_url: str


class ExportAndImportDataFormat(BaseModel):
    agent_id: int
    agent_info: Dict[str, ExportAndImportAgentInfo]
    mcp_info: List[MCPInfo]


class AgentRepositorySnapshot(ExportAndImportDataFormat):
    """Frozen marketplace snapshot: export format plus optional skill ZIP payloads."""

    skills: Optional[List["SkillZipEntry"]] = None


RepositoryImportRequirementType = Literal["model", "knowledge_base", "mcp", "skill", "tool"]


class RepositoryImportRequirementItem(BaseModel):
    """Single dependency item for repository import precheck."""

    type: RepositoryImportRequirementType
    key: str
    name: str
    description: Optional[str] = None
    available: bool
    reason_code: Optional[str] = None


class RepositoryImportPrecheckResponse(BaseModel):
    """Response payload for repository import precheck."""

    agent_repository_id: int
    display_name: str
    total_count: int
    available_count: int
    percent: int
    has_abnormal: bool
    items: List[RepositoryImportRequirementItem]


class AgentRepositoryListingCreateRequest(BaseModel):
    """Request body for creating a marketplace listing from an agent version."""

    icon: Optional[str] = Field(None, description="Marketplace card icon (emoji or URL)")
    downloads: int = Field(0, ge=0, description="Initial download/copy count for card display")
    tags: Optional[List[str]] = Field(None, description="Marketplace tags")
    category_id: Optional[int] = Field(0, description="Optional marketplace category ID")
    tool_count: Optional[int] = Field(
        None, ge=0, description="Total tool count across all agents in the bundle"
    )
    content: Optional[str] = Field(
        None, description="Listing note when submitting for review"
    )


class AgentRepositoryCategoryItem(BaseModel):
    """Marketplace category option for agent repository filtering."""

    id: int
    key: str
    name: str


class AgentRepositoryListingDetailResponse(BaseModel):
    """Detailed marketplace listing payload for repository detail view."""

    agent_repository_id: int
    agent_id: Optional[int] = None
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    icon: Optional[str] = None
    status: str
    version_label: Optional[str] = None
    downloads: int = 0
    created_at: Optional[str] = None
    model_name: Optional[str] = None
    duty_prompt: Optional[str] = None
    tools: List[str] = Field(default_factory=list)


class SkillRepositoryListingCreateRequest(BaseModel):
    """Request body for creating a marketplace listing from a skill snapshot."""
    icon: Optional[str] = Field(None, description="Marketplace card icon (emoji or URL)")
    downloads: int = Field(0, ge=0, description="Initial download count for card display")
    tags: Optional[List[str]] = Field(None, description="Marketplace tags")
    category_id: Optional[int] = Field(0, description="Optional marketplace category ID")


class SkillRepositoryInstallRequest(BaseModel):
    """Request body for installing a repository skill into current tenant."""
    target_name: Optional[str] = Field(None, description="Target skill name in current tenant")


class SkillRepositoryListingDetailResponse(BaseModel):
    """Detailed marketplace listing payload for skill repository detail view."""
    skill_repository_id: int
    skill_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    source: Optional[str] = None
    submitted_by: Optional[str] = None
    icon: Optional[str] = None
    status: str
    category_id: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    downloads: int = 0
    created_at: Optional[str] = None
    content: Optional[str] = None
    config_schemas: Optional[Dict[str, Any]] = None
    config_values: Optional[Dict[str, Any]] = None
    tool_ids: List[int] = Field(default_factory=list)


class SkillZipEntry(BaseModel):
    """A skill bundled inside an agent export ZIP."""

    skill_name: str
    skill_zip_base64: str


class AgentImportRequest(BaseModel):
    agent_info: ExportAndImportDataFormat
    force_import: bool = False
    skills: Optional[List[SkillZipEntry]] = None


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

    model_type: str = Field(..., description="Type of model to check ('stt' or 'tts')")


class VoiceConnectivityResponse(BaseModel):
    """Response model for voice service connectivity check"""

    connected: bool = Field(..., description="Whether the service is connected")
    model_type: str = Field(..., description="Type of model checked")
    message: str = Field(..., description="Status message")


class ToolValidateRequest(BaseModel):
    """Request model for tool validation"""

    name: str = Field(..., description="Tool name to validate")
    source: str = Field(..., description="Tool source (local, mcp, langchain)")
    usage: Optional[str] = Field(None, description="Tool usage information")
    inputs: Optional[Dict[str, Any]] = Field(None, description="Tool inputs")
    params: Optional[Dict[str, Any]] = Field(None, description="Tool configuration parameters")


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server"""

    command: str = Field(..., description="Command to run (e.g., 'npx')")
    args: List[str] = Field(default_factory=list, description="Command arguments")
    env: Optional[Dict[str, str]] = Field(None, description="Environment variables for the MCP server")
    port: Optional[int] = Field(None, description="Host port to expose the MCP server on (e.g., 5020)")
    image: Optional[str] = Field(
        None,
        description="Docker image for the MCP proxy container (optional, overrides MCP_DOCKER_IMAGE)",
    )


class MCPConfigRequest(BaseModel):
    """Request model for adding MCP servers from configuration"""

    mcpServers: Dict[str, MCPServerConfig] = Field(..., description="Dictionary of MCP server configurations")


class UpdateKnowledgeListRequest(BaseModel):
    """Request model for updating user's selected knowledge base list grouped by source"""

    nexent: Optional[List[str]] = Field(None, description="List of knowledge base index names from nexent source")
    datamate: Optional[List[str]] = Field(None, description="List of knowledge base index names from datamate source")


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
    custom_headers: Optional[Dict[str, Any]] = Field(None, description="Custom HTTP headers as JSON object")


# Tenant Management Data Models
# ---------------------------------------------------------------------------
class TenantCreateRequest(BaseModel):
    """Request model for creating a tenant"""

    tenant_name: str = Field(..., min_length=1, description="Tenant display name")
    skill_ids: Optional[List[int]] = Field(
        default=None,
        description="Skill IDs to install for the new tenant (legacy, use skill_names instead)",
    )
    skill_names: Optional[List[str]] = Field(
        default=None,
        description="Skill names to install for the new tenant. "
        "Each name is used to derive a .zip filename from "
        "OFFICIAL_SKILLS_ZIP_PATH and installed via upload.",
    )
    locale: Optional[str] = Field(
        default=None,
        description="Frontend locale when creating the tenant (e.g. 'zh' or 'en'). "
        "Determines the source label for auto-installed skills: "
        "'zh' → '官方', other locales → 'official'.",
    )


class TenantUpdateRequest(BaseModel):
    """Request model for updating tenant information"""

    tenant_name: str = Field(..., min_length=1, description="New tenant display name")


# Pagination request model
class PaginationRequest(BaseModel):
    """Request model for pagination parameters"""

    page: int = Field(1, ge=1, description="Page number")
    page_size: int = Field(20, ge=1, le=100, description="Items per page")


# Group Management Data Models
# ---------------------------------------------------------------------------
class GroupCreateRequest(BaseModel):
    """Request model for creating a group"""

    tenant_id: str = Field(..., min_length=1, description="Tenant ID where the group belongs")
    group_name: str = Field(..., min_length=1, description="Group display name")
    group_description: Optional[str] = Field(None, description="Optional group description")


class GroupUpdateRequest(BaseModel):
    """Request model for updating group information"""

    group_name: Optional[str] = Field(None, description="New group name")
    group_description: Optional[str] = Field(None, description="New group description")


class GroupListRequest(BaseModel):
    """Request model for listing groups"""

    tenant_id: str = Field(..., description="Tenant ID to filter groups")
    page: Optional[int] = Field(
        None,
        ge=1,
        description="Page number for pagination. If not provided, returns all data",
    )
    page_size: Optional[int] = Field(
        None,
        ge=1,
        le=100,
        description="Number of items per page. If not provided, returns all data",
    )
    sort_by: Optional[str] = Field("created_at", description="Field to sort by")
    sort_order: Optional[str] = Field("desc", description="Sort order (asc or desc)")


class UserListRequest(BaseModel):
    """Request model for listing users"""

    tenant_id: str = Field(..., description="Tenant ID to filter users")
    page: Optional[int] = Field(
        None,
        ge=1,
        description="Page number for pagination. If not provided, returns all data",
    )
    page_size: Optional[int] = Field(
        None,
        ge=1,
        le=100,
        description="Number of items per page. If not provided, returns all data",
    )
    sort_by: Optional[str] = Field("created_at", description="Field to sort by")
    sort_order: Optional[str] = Field("desc", description="Sort order (asc or desc)")


class GroupUserRequest(BaseModel):
    """Request model for adding/removing user from group"""

    user_id: str = Field(..., min_length=1, description="User ID to add/remove")
    group_ids: Optional[List[int]] = Field(None, description="List of group IDs (for batch operations)")


class GroupMembersUpdateRequest(BaseModel):
    """Request model for batch updating group members"""

    user_ids: List[str] = Field(..., description="List of user IDs to set as group members")


class SetDefaultGroupRequest(BaseModel):
    """Request model for setting tenant's default group"""

    default_group_id: int = Field(..., ge=1, description="Group ID to set as default for the tenant")


# Invitation Management Data Models
# ---------------------------------------------------------------------------
class InvitationCreateRequest(BaseModel):
    """Request model for creating invitation code"""

    tenant_id: str = Field(..., min_length=1, description="Tenant ID where the invitation belongs")
    code_type: str = Field(..., description="Invitation code type (ADMIN_INVITE, DEV_INVITE, USER_INVITE)")
    invitation_code: Optional[str] = Field(None, description="Custom invitation code (auto-generated if not provided)")
    group_ids: Optional[List[int]] = Field(None, description="Associated group IDs")
    capacity: int = Field(default=1, ge=1, description="Maximum usage capacity")
    expiry_date: Optional[str] = Field(None, description="Expiry date in ISO format")


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
    group_ids: Optional[List[int]] = Field(None, description="Associated group IDs")
    capacity: int = Field(..., description="Usage capacity")
    expiry_date: Optional[str] = Field(None, description="Expiry date")
    status: str = Field(..., description="Current status")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")


class InvitationListRequest(BaseModel):
    """Request model for listing invitation codes"""

    tenant_id: Optional[str] = Field(None, description="Tenant ID to filter by (optional)")
    page: int = Field(1, ge=1, description="Page number for pagination")
    page_size: int = Field(20, ge=1, le=100, description="Number of items per page")
    sort_by: Optional[str] = Field(None, description="Sort field (create_time, update_time, etc.)")
    sort_order: Optional[str] = Field(None, description="Sort order (asc, desc)")


class InvitationUseResponse(BaseModel):
    """Response model for invitation usage"""

    invitation_record_id: int = Field(..., description="Usage record ID")
    invitation_code: str = Field(..., description="Used invitation code")
    user_id: str = Field(..., description="User who used the code")
    invitation_id: int = Field(..., description="Invitation ID")
    code_type: str = Field(..., description="Code type")
    group_ids: Optional[List[int]] = Field(None, description="Associated group IDs")


# Manage Tenant Model Data Models
# ---------------------------------------------------------------------------
class ManageTenantModelListRequest(BaseModel):
    """Request model for listing models in a specific tenant (manage operation)"""

    tenant_id: str = Field(..., min_length=1, description="Target tenant ID to query models for")
    model_type: Optional[str] = Field(None, description="Filter by model type (e.g., 'llm', 'embedding')")
    page: int = Field(1, ge=1, description="Page number for pagination")
    page_size: int = Field(20, ge=1, le=100, description="Items per page")


class ManageTenantModelListResponse(BaseModel):
    """Response model for tenant model list query"""

    tenant_id: str = Field(..., description="Tenant identifier")
    tenant_name: str = Field(..., description="Tenant display name")
    models: List[Dict[str, Any]] = Field(default_factory=list, description="List of models for this tenant")
    total: int = Field(0, description="Total number of models")
    page: int = Field(1, description="Current page number")
    page_size: int = Field(20, description="Items per page")
    total_pages: int = Field(0, description="Total number of pages")


class ManageTenantModelCreateRequest(BaseModel):
    """Request model for creating a model in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(..., min_length=1, description="Target tenant ID to create model for")
    model_repo: Optional[str] = Field("", description="Model repository path")
    model_name: str = Field(..., description="Model name")
    model_type: str = Field(..., description="Model type (e.g., 'llm', 'embedding', 'vlm', 'stt')")
    api_key: Optional[str] = Field("", description="API key for the model")
    base_url: Optional[str] = Field("", description="Base URL for the model API")
    max_tokens: Optional[int] = Field(0, description="Maximum tokens for the model")
    display_name: Optional[str] = Field("", description="Display name for the model")
    model_factory: Optional[str] = Field(None, description="Model factory/vendor for the model")
    expected_chunk_size: Optional[int] = Field(None, description="Expected chunk size for embedding models")
    maximum_chunk_size: Optional[int] = Field(None, description="Maximum chunk size for embedding models")
    chunk_batch: Optional[int] = Field(None, description="Batch size for chunking")
    # STT specific fields
    model_appid: Optional[str] = Field(None, description="Application ID for STT models (e.g., Volcano Engine)")
    access_token: Optional[str] = Field(None, description="Access token for STT models (e.g., Volcano Engine)")
    timeout_seconds: Optional[int] = Field(None, description="Request timeout in seconds")
    concurrency_limit: Optional[int] = Field(None, description="Maximum concurrent requests for this model")
    # W1 capacity fields (see W1 ADR). All nullable; resolver applies precedence.
    context_window_tokens: Optional[int] = Field(None, description="Total combined input/output context window in tokens")
    max_input_tokens: Optional[int] = Field(None, description="Provider hard input-token limit")
    max_output_tokens: Optional[int] = Field(None, description="Provider-supported completion output cap")
    default_output_reserve_tokens: Optional[int] = Field(None, description="Default output allowance reserved per request")
    tokenizer_family: Optional[str] = Field(None, description="Token-counting strategy or tokenizer identifier")
    capacity_source: Optional[str] = Field(None, description="Source of the persisted capacity value")
    capability_profile_version: Optional[str] = Field(None, description="Version of the approved capability profile")
    # W11 accept-signal fields. Same audit-only contract as ModelRequest:
    # the app layer pops them off model_data before the dict reaches the
    # service/DB layer and forwards them to
    # model_capacity_suggestion_accept_total. Declared here so Pydantic's
    # default extra="ignore" does not silently drop the wire signal --
    # without these declarations the SLO numerator misses every accept
    # that lands via the SU/asset-owner surface.
    accepted_suggestion_match_kind: Optional[str] = Field(
        None, description="Audit-only: catalog match_kind the operator accepted"
    )
    accepted_capability_profile_version: Optional[str] = Field(
        None,
        description="Audit-only: capability profile version of the accepted suggestion",
    )


class ManageTenantModelUpdateRequest(BaseModel):
    """Request model for updating a model in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(..., min_length=1, description="Target tenant ID to update model for")
    current_display_name: str = Field(..., description="Current display name of the model to update")
    model_repo: Optional[str] = Field(None, description="Model repository path")
    model_name: Optional[str] = Field(None, description="Model name")
    model_type: Optional[str] = Field(None, description="Model type")
    api_key: Optional[str] = Field(None, description="API key for the model")
    base_url: Optional[str] = Field(None, description="Base URL for the model API")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens for the model")
    display_name: Optional[str] = Field(None, description="New display name for the model")
    model_factory: Optional[str] = Field(None, description="Model factory/vendor for the model")
    expected_chunk_size: Optional[int] = Field(None, description="Expected chunk size for embedding models")
    maximum_chunk_size: Optional[int] = Field(None, description="Maximum chunk size for embedding models")
    chunk_batch: Optional[int] = Field(None, description="Batch size for chunking")
    # STT specific fields
    model_appid: Optional[str] = Field(None, description="Application ID for STT models")
    access_token: Optional[str] = Field(None, description="Access token for STT models")
    timeout_seconds: Optional[int] = Field(None, description="Request timeout in seconds")
    concurrency_limit: Optional[int] = Field(None, description="Maximum concurrent requests for this model")
    # W1 capacity fields (see W1 ADR). All nullable; resolver applies precedence.
    context_window_tokens: Optional[int] = Field(None, description="Total combined input/output context window in tokens")
    max_input_tokens: Optional[int] = Field(None, description="Provider hard input-token limit")
    max_output_tokens: Optional[int] = Field(None, description="Provider-supported completion output cap")
    default_output_reserve_tokens: Optional[int] = Field(None, description="Default output allowance reserved per request")
    tokenizer_family: Optional[str] = Field(None, description="Token-counting strategy or tokenizer identifier")
    capacity_source: Optional[str] = Field(None, description="Source of the persisted capacity value")
    capability_profile_version: Optional[str] = Field(None, description="Version of the approved capability profile")
    # W11 accept-signal fields. See ManageTenantModelCreateRequest for the
    # contract. The app layer pops them before calling the service so
    # update_model_record never sees them.
    accepted_suggestion_match_kind: Optional[str] = Field(
        None, description="Audit-only: catalog match_kind the operator accepted"
    )
    accepted_capability_profile_version: Optional[str] = Field(
        None,
        description="Audit-only: capability profile version of the accepted suggestion",
    )


class ManageTenantModelDeleteRequest(BaseModel):
    """Request model for deleting a model from a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(..., min_length=1, description="Target tenant ID to delete model from")
    display_name: str = Field(..., description="Display name of the model to delete")


class ManageTenantModelHealthcheckRequest(BaseModel):
    """Request model for checking model connectivity in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(..., min_length=1, description="Target tenant ID to check model connectivity")
    display_name: str = Field(..., description="Display name of the model to check")
    model_type: Optional[str] = Field(
        None,
        description="Model type to disambiguate models with the same display name",
    )


class ManageBatchCreateModelsRequest(BaseModel):
    """Request model for batch creating/updating models in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(..., min_length=1, description="Target tenant ID to batch create models for")
    provider: str = Field(..., description="Model provider (e.g., 'silicon', 'modelengine')")
    type: str = Field(..., description="Model type (e.g., 'llm', 'embedding')")
    api_key: str = Field("", description="API key for the models")
    models: List[Dict[str, Any]] = Field(default_factory=list, description="List of models to create/update")


class ManageProviderModelListRequest(BaseModel):
    """Request model for listing provider models in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(..., min_length=1, description="Target tenant ID to query provider models for")
    provider: str = Field(..., description="Model provider (e.g., 'silicon', 'modelengine')")
    model_type: str = Field(..., description="Model type (e.g., 'llm', 'embedding')")


class ManageProviderModelCreateRequest(BaseModel):
    """Request model for creating provider models in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(..., min_length=1, description="Target tenant ID to create provider models for")
    provider: str = Field(..., description="Model provider (e.g., 'silicon', 'modelengine')")
    model_type: str = Field(..., description="Model type (e.g., 'llm', 'embedding')")
    api_key: Optional[str] = Field("", description="API key for the provider")
    base_url: Optional[str] = Field("", description="Base URL for the provider API")


# Agent Version Management Data Models
# ---------------------------------------------------------------------------
class VersionPublishRequest(BaseModel):
    """Request model for publishing a new version"""

    version_name: Optional[str] = Field(None, description="User-defined version name for display")
    release_note: Optional[str] = Field(None, description="Release notes / publish remarks")
    publish_as_a2a: bool = Field(False, description="Whether to publish this agent as an A2A Server agent")


class VersionListItemResponse(BaseModel):
    """Response model for version list item"""

    id: int = Field(..., description="Version record ID")
    version_no: int = Field(..., description="Version number")
    version_name: Optional[str] = Field(None, description="User-defined version name")
    release_note: Optional[str] = Field(None, description="Release notes")
    source_version_no: Optional[int] = Field(None, description="Source version number if rollback")
    source_type: Optional[str] = Field(None, description="Source type: NORMAL / ROLLBACK")
    status: str = Field(..., description="Version status: RELEASED / DISABLED / ARCHIVED")
    is_a2a: bool = Field(False, description="Whether this version is published as an A2A Server agent")
    created_by: str = Field(..., description="User who published this version")
    create_time: Optional[str] = Field(None, description="Publish timestamp")


class VersionListResponse(BaseModel):
    """Response model for version list"""

    items: List[VersionListItemResponse] = Field(..., description="Version list items")
    total: int = Field(..., description="Total count")


class VersionDetailResponse(BaseModel):
    """Response model for version detail including snapshot data"""

    id: int = Field(..., description="Version record ID")
    version_no: int = Field(..., description="Version number")
    version_name: Optional[str] = Field(None, description="User-defined version name")
    release_note: Optional[str] = Field(None, description="Release notes")
    source_version_no: Optional[int] = Field(None, description="Source version number")
    source_type: Optional[str] = Field(None, description="Source type")
    status: str = Field(..., description="Version status")
    is_a2a: bool = Field(False, description="Whether this version is published as an A2A Server agent")
    created_by: str = Field(..., description="User who published this version")
    create_time: Optional[str] = Field(None, description="Publish timestamp")
    agent_info: Optional[dict] = Field(None, description="Agent info snapshot")
    tool_instances: List[dict] = Field(default_factory=list, description="Tool instance snapshots")
    relations: List[dict] = Field(default_factory=list, description="Relation snapshots")


class VersionRollbackRequest(BaseModel):
    """Request model for rollback to a specific version"""

    version_name: Optional[str] = Field(None, description="New version name for the rollback version")
    release_note: Optional[str] = Field(None, description="Release notes for the rollback version")


class VersionStatusRequest(BaseModel):
    """Request model for updating version status"""

    status: str = Field(..., description="New status: DISABLED / ARCHIVED")


class VersionUpdateRequest(BaseModel):
    """Request model for updating version metadata (name and description)"""

    version_name: Optional[str] = Field(None, description="User-defined version name for display")
    release_note: Optional[str] = Field(None, description="Release notes / version description")


class VersionCompareRequest(BaseModel):
    """Request model for comparing two versions"""

    version_no_a: int = Field(..., description="First version number for comparison")
    version_no_b: int = Field(..., description="Second version number for comparison")


class CurrentVersionResponse(BaseModel):
    """Response model for current published version"""

    version_no: int = Field(..., description="Current published version number")
    version_name: Optional[str] = Field(None, description="Version name")
    status: str = Field(..., description="Version status")
    source_type: Optional[str] = Field(None, description="Source type")
    source_version_no: Optional[int] = Field(None, description="Source version number")
    release_note: Optional[str] = Field(None, description="Release notes")
    created_by: str = Field(..., description="User who published this version")
    create_time: Optional[str] = Field(None, description="Publish timestamp")


# Skill Management Data Models
# ---------------------------------------------------------------------------
class SkillCreateRequest(BaseModel):
    """Request model for creating a skill via JSON."""

    name: str
    description: str
    content: str
    tool_ids: Optional[List[int]] = []
    tool_names: Optional[List[str]] = []
    tags: Optional[List[str]] = []
    source: Optional[str] = "custom"
    config_schemas: Optional[Dict[str, Any]] = None
    config_values: Optional[Dict[str, Any]] = None
    files: Optional[List[Dict[str, str]]] = Field(
        default_factory=list,
        description="Additional skill files beyond SKILL.md. "
        "Each entry has 'path' (relative path) and 'content'. "
        "SKILL.md may also be sent here; the 'content' field is the primary SKILL.md source.",
    )


class SkillFileData(BaseModel):
    """A single file within a skill."""

    path: str = Field(description="Relative file path within the skill (e.g. 'SKILL.md', 'scripts/run.py')")
    content: str = Field(description="Full file content")


class SkillUpdateRequest(BaseModel):
    """Request model for updating a skill."""
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    tool_ids: Optional[List[int]] = None
    tool_names: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = None
    config_schemas: Optional[Dict[str, Any]] = None
    config_values: Optional[Dict[str, Any]] = None
    files: Optional[List[SkillFileData]] = Field(
        default_factory=list,
        description="Updated skill files. Each entry has file_path and content. "
        "Pass 'SKILL.md' here to update the main skill file; other files are written as-is.",
    )


class SkillResponse(BaseModel):
    """Response model for skill data."""

    skill_id: int
    name: str
    description: str
    content: str
    tool_ids: List[int]
    tags: List[str]
    source: str
    config_schemas: Optional[Dict[str, Any]] = None
    config_values: Optional[Dict[str, Any]] = None
    created_by: Optional[str] = None
    create_time: Optional[str] = None
    updated_by: Optional[str] = None
    update_time: Optional[str] = None


class SkillCreateInteractiveRequest(BaseModel):
    """Request model for interactive skill creation via LLM agent."""

    user_request: str
    existing_skill: Optional[Dict[str, Any]] = None
    complexity: Optional[str] = "simple"
    language: Optional[str] = "zh"


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
    source: MCPSourceType = Field(default=MCPSourceType.LOCAL, description="MCP source type")
    tags: List[str] = Field(default_factory=list, description="MCP tags")
    authorization_token: Optional[str] = Field(None, description="Authorization token for MCP server")
    custom_headers: Optional[Dict[str, Any]] = Field(None, description="Custom HTTP headers as JSON object")
    container_config: Optional[Dict[str, Any]] = Field(None, description="Container configuration")
    registry_json: Optional[Dict[str, Any]] = Field(None, description="Registry metadata JSON")
    config_json: Optional[Dict[str, Any]] = Field(None, description="MCP configuration JSON (e.g. OpenAPI spec for API-type MCP)")
    market_id: Optional[int] = Field(None, gt=0, description="Linked market record ID")
    enabled: Optional[bool] = Field(default=False, description="Whether the MCP is enabled after creation")

    @field_validator("name", "server_url", "description", "authorization_token", mode="before")
    @classmethod
    def _strip_text(cls, value: Any):
        if isinstance(value, str):
            return value.strip()
        return value


class AddContainerMcpServiceRequest(BaseModel):
    """Request model for adding a container-based MCP service"""

    name: str = Field(..., min_length=1, description="MCP service name")
    description: Optional[str] = Field(None, description="MCP service description")
    source: MCPSourceType = Field(default=MCPSourceType.LOCAL, description="MCP source type")
    tags: List[str] = Field(default_factory=list, description="MCP tags")
    authorization_token: Optional[str] = Field(None, description="Authorization token for MCP server")
    registry_json: Optional[Dict[str, Any]] = Field(None, description="Registry metadata JSON")
    market_id: Optional[int] = Field(None, gt=0, description="Linked market record ID")
    port: int = Field(..., ge=1, le=65535, description="Host port for the container")
    mcp_config: MCPConfigRequest = Field(..., description="MCP server configuration")

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
    server_url: str = Field(..., min_length=1, description="New MCP server URL")
    tags: List[str] = Field(default_factory=list, description="MCP tags")
    authorization_token: Optional[str] = Field(None, description="Authorization token for MCP server")
    custom_headers: Optional[Dict[str, Any]] = Field(None, description="Custom HTTP headers as JSON object")
    config_json: Optional[Dict[str, Any]] = Field(None, description="MCP configuration JSON")
    version: Optional[str] = Field(None, description="MCP version")
    market_id: Optional[int] = Field(None, gt=0, description="Linked market record ID")

    @field_validator("name", "server_url", "description", "authorization_token", "version", mode="before")
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
    authorization_token: Optional[str] = Field(None, description="Authorization token for MCP server")
    custom_headers: Optional[Dict[str, Any]] = Field(None, description="Custom HTTP headers as JSON object")


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


class RegistryListQuery(BaseModel):
    """Query parameters for listing MCP registry services"""

    search: Optional[str] = Field(None, description="Search keyword")
    include_deleted: bool = Field(default=False, description="Include deleted records")
    updated_since: Optional[str] = Field(None, description="Filter by update time")
    version: Optional[str] = Field(None, description="Filter by version")
    cursor: Optional[str] = Field(None, description="Pagination cursor")
    limit: int = Field(default=30, ge=1, le=100, description="Items per page")

    @field_validator("search", "updated_since", "version", "cursor", mode="before")
    @classmethod
    def _strip_text(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class CommunityListRequest(BaseModel):
    """Request model for listing community MCP services"""

    search: Optional[str] = Field(None, description="Search keyword")
    tag: Optional[str] = Field(None, description="Filter by tag")
    transport_type: Optional[str] = Field(None, description="Filter by transport: url or container")
    cursor: Optional[str] = Field(None, description="Pagination cursor")
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
    config_json: Optional[Dict[str, Any]] = Field(None, description="Container MCP configuration JSON override")

    @field_validator("name", "description", "mcp_server", mode="before")
    @classmethod
    def _strip_publish_optional_text(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class CommunityUpdateRequest(BaseModel):
    """Request model for updating community MCP service"""
    market_id: int = Field(..., gt=0, description="Market record ID")
    name: Optional[str] = Field(default=None, min_length=1, description="New MCP service name")
    description: Optional[str] = Field(None, description="MCP service description")
    tags: List[str] = Field(default_factory=list, description="MCP tags")
    registry_json: Optional[Dict[str, Any]] = Field(None, description="Registry metadata JSON")
    mcp_server: Optional[str] = Field(None, max_length=500, description="MCP server URL")
    transport_type: Optional[str] = Field(None, description="Transport type")
    config_json: Optional[Dict[str, Any]] = Field(
        None,
        description="Container MCP configuration JSON (omit to leave unchanged)",
    )

    @field_validator("name", "description", "mcp_server", "transport_type", mode="before")
    @classmethod
    def _strip_text(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class CommunityStatusUpdateRequest(BaseModel):
    """Request model for changing MCP market listing status (PATCH)."""
    status: str = Field(..., description="New status: shared / rejected / not_shared / pending_review")


class DeleteMcpServiceRequest(BaseModel):
    """Request model for deleting an MCP service"""

    mcp_id: int = Field(..., gt=0, description="MCP record ID to delete")
