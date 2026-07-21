"""Typed HTTP responses for the NL2AGENT workflow API."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from agents.nl2agent_workflow import (
    CardDelivery,
    CardType,
    OnlineRecommendationBatch,
    RecommendationBatch,
    RequirementsReview,
    TrustedSearchBatch,
)


class Nl2AgentResponse(BaseModel):
    """Strict base model for public NL2AGENT response contracts."""

    model_config = ConfigDict(extra="forbid")


class Nl2AgentContinuationResponse(Nl2AgentResponse):
    agent_id: int
    chat_injection_text: Optional[str] = None


class Nl2AgentSessionStartResponse(Nl2AgentResponse):
    nl2agent_agent_id: int
    draft_agent_id: int
    conversation_id: int
    draft_name: str


class Nl2AgentSessionSummaryResponse(Nl2AgentResponse):
    nl2agent_agent_id: int
    draft_agent_id: int
    conversation_id: int
    status: Literal["active", "completed", "abandoned"]
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


class Nl2AgentSessionListResponse(Nl2AgentResponse):
    sessions: List[Nl2AgentSessionSummaryResponse]


class Nl2AgentModelSummary(Nl2AgentResponse):
    model_id: int
    display_name: str


class Nl2AgentModelSelectionResponse(Nl2AgentContinuationResponse):
    primary_model_id: int
    fallback_model_ids: List[int]
    models: List[Nl2AgentModelSummary]


class Nl2AgentDiscoveredTool(Nl2AgentResponse):
    tool_id: int
    name: str
    description: Optional[str] = None


class Nl2AgentMcpInstallResponse(Nl2AgentResponse):
    agent_id: int
    mcp_id: int
    status: Literal["connected"]
    tools: List[Nl2AgentDiscoveredTool]


class Nl2AgentMcpBindToolsResponse(Nl2AgentResponse):
    agent_id: int
    mcp_id: int
    bound_tool_ids: List[int]


class Nl2AgentMcpSkipToolsResponse(Nl2AgentResponse):
    agent_id: int
    mcp_id: int
    status: Literal["binding_skipped"]


class Nl2AgentApplyLocalResourcesResponse(Nl2AgentResponse):
    recommendation_batch_id: str
    status: Literal["applied"]
    bound_tool_count: int
    bound_skill_count: int
    tool_ids: List[int]
    skill_ids: List[int]
    chat_injection_text: str


class Nl2AgentToolParameterSchema(Nl2AgentResponse):
    model_config = ConfigDict(extra="allow")

    name: str
    type: Optional[str] = None
    description: Optional[str] = None
    default: Optional[Any] = None
    required: Optional[bool] = None
    optional: Optional[bool] = None
    isSecret: Optional[bool] = None
    is_secret: Optional[bool] = None
    choices: Optional[List[Any]] = None


class Nl2AgentLocalRecommendationResponse(Nl2AgentResponse):
    recommendation_batch_id: str
    status: Literal["recommendations_ready", "applying", "applied", "skipped"]
    tool_ids: List[int]
    skill_ids: List[int]
    applied_tool_ids: List[int]
    applied_skill_ids: List[int]
    tool_parameter_schemas: Dict[str, List[Nl2AgentToolParameterSchema]]


class Nl2AgentLocalSkipResponse(Nl2AgentResponse):
    recommendation_batch_id: str
    status: Literal["skipped"]
    tool_ids: List[int]
    skill_ids: List[int]
    applied_tool_ids: List[int]
    applied_skill_ids: List[int]
    chat_injection_text: str


class Nl2AgentOnlineRecommendationResponse(Nl2AgentResponse):
    recommendation_batch_id: str
    resource_type: Literal["mcp", "skill"]
    item_keys: List[str]
    status: Literal["recommendations_ready", "completed"]


class Nl2AgentRequirementsData(Nl2AgentResponse):
    goal: str
    audience_or_scenario: str
    primary_input: str
    expected_output: str
    key_constraints: str


class Nl2AgentRequirementsRegistrationResponse(Nl2AgentResponse):
    agent_id: int
    status: Literal["collecting", "awaiting_confirmation", "confirmed"]
    summary: Nl2AgentRequirementsData
    fingerprint: str
    is_current: bool


class Nl2AgentRequirementsConfirmationResponse(Nl2AgentContinuationResponse):
    status: Literal["confirmed"]
    fingerprint: str


class Nl2AgentCardDeliveryResponse(Nl2AgentContinuationResponse):
    message_id: int
    card_type: CardType
    status: Literal["rendered", "failed"]
    card_key: Optional[str] = None
    reason: Optional[str] = None
    retry_count: int = 0
    auto_retry_allowed: bool


class Nl2AgentOnlineConfigurationResponse(Nl2AgentContinuationResponse):
    online_configuration_confirmed: bool
    completed_batch_ids: List[str]


class Nl2AgentRequirementsReviewResponse(RequirementsReview):
    summary: Optional[Nl2AgentRequirementsData] = None


class Nl2AgentMcpWorkflowResponse(Nl2AgentResponse):
    recommendation_id: str
    option_id: Optional[str] = None
    installation_key: Optional[str] = None
    status: Optional[
        Literal[
            "configuration_required",
            "installing",
            "connected",
            "tools_bound",
            "binding_skipped",
            "failed",
        ]
    ] = None
    mcp_id: Optional[int] = None
    discovered_tool_ids: List[int] = Field(default_factory=list)
    bound_tool_ids: List[int] = Field(default_factory=list)
    discovered_tools: List[Nl2AgentDiscoveredTool] = Field(default_factory=list)
    error: Optional[str] = None


class Nl2AgentWorkflowStateResponse(Nl2AgentResponse):
    schema_version: Literal[2] = 2
    revision: int = 0
    conversation_id: int
    requirements_review: Nl2AgentRequirementsReviewResponse
    model_selection_confirmed: bool = False
    trusted_search_batches: Dict[str, TrustedSearchBatch] = Field(
        default_factory=dict
    )
    recommendation_batches: Dict[str, RecommendationBatch] = Field(
        default_factory=dict
    )
    identity_confirmed: bool = False
    mcp_workflows: Dict[str, Nl2AgentMcpWorkflowResponse]
    online_recommendation_batches: Dict[str, OnlineRecommendationBatch] = Field(
        default_factory=dict
    )
    online_configuration_confirmed: bool = False
    card_delivery: Dict[CardType, CardDelivery] = Field(default_factory=dict)


class Nl2AgentPersistedModel(Nl2AgentResponse):
    model_id: int
    display_name: Optional[str] = None
    role: Literal["primary", "fallback"]
    valid: bool


class Nl2AgentToolConfigurationField(Nl2AgentResponse):
    value: Optional[Any] = None
    configured: bool = False
    secret: bool = False


class Nl2AgentToolSummary(Nl2AgentResponse):
    tool_id: int
    name: str
    source: str
    origin: Literal["local", "online"]
    parameter_schema: List[Nl2AgentToolParameterSchema] = Field(default_factory=list)
    configuration: Dict[str, Nl2AgentToolConfigurationField] = Field(
        default_factory=dict
    )


class Nl2AgentSkillSummary(Nl2AgentResponse):
    skill_id: int
    name: str
    source: str
    origin: Literal["local", "online"]


class Nl2AgentInvalidReference(Nl2AgentResponse):
    reference_type: Literal["model", "tool", "skill"]
    reference_id: int
    reason: Literal[
        "not_found",
        "not_llm",
        "unavailable",
        "name_missing",
        "primary_not_in_runtime_models",
    ]


class Nl2AgentSessionStateResponse(Nl2AgentResponse):
    agent_id: int
    session_status: Literal["active", "completed"]
    schema_version: Literal[2]
    revision: int
    current_stage: Literal[
        "requirements_collecting",
        "requirements_confirmation",
        "model_selection",
        "local_resource_search",
        "local_resource_review",
        "online_resource_search",
        "online_resource_review",
        "agent_identity",
        "final_review",
    ]
    expected_card_types: List[CardType]
    allowed_actions: List[str]
    display_name: Optional[str] = None
    internal_name: str
    identity_confirmed: bool
    business_logic_model_id: Optional[int] = None
    model_ids: List[int]
    models: List[Nl2AgentPersistedModel]
    tools: List[Nl2AgentToolSummary]
    skills: List[Nl2AgentSkillSummary]
    local_tool_parameter_schemas: Dict[
        str, Dict[str, List[Nl2AgentToolParameterSchema]]
    ] = Field(default_factory=dict)
    invalid_references: List[Nl2AgentInvalidReference]
    resource_review: Nl2AgentWorkflowStateResponse


class Nl2AgentIdentityResponse(Nl2AgentContinuationResponse):
    display_name: str
    internal_name: str
    identity_confirmed: bool


class Nl2AgentWebSkillInstallResponse(Nl2AgentResponse):
    skill_id: int
    skill_name: Optional[str] = None
    installed: bool
    bound: bool
    installed_ids: List[int]
    installed_names: Optional[List[str]] = None


class Nl2AgentSkillParameterSchema(Nl2AgentResponse):
    model_config = ConfigDict(extra="allow")

    name: str
    type: Optional[str] = None
    required: bool = False
    optional: Optional[bool] = None
    value: Optional[Any] = None
    default: Optional[Any] = None
    choices: Optional[List[Any]] = None
    description_en: Optional[str] = None
    description_zh: Optional[str] = None
    depends_on: Optional[str] = None
    isSecret: Optional[bool] = None
    is_secret: Optional[bool] = None


class Nl2AgentWebSkillConfigurationResponse(Nl2AgentResponse):
    skill_id: Optional[int] = None
    skill_name: str
    config_schemas: List[Nl2AgentSkillParameterSchema] = Field(default_factory=list)
    config_values: Dict[str, Any] = Field(default_factory=dict)


class Nl2AgentFinalizeResponse(Nl2AgentResponse):
    agent_id: int
    status: Literal["draft_ready"]
    name: str
    display_name: str
    tool_ids: List[int]
    skill_ids: List[int]
