# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared Agent projections, system references and preparation values."""

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional
from typing import Optional as Opt

from contracts.clarification import ClarificationResponse
from contracts.constants.constants import WORKBENCH_OFFICIAL_SKILL_NAMES
from contracts.conversation import HistoryItem
from contracts.knowledge import ConversationKnowledgeScopeRequest, WorkbenchMode
from contracts.skill import SkillResolution, SkillZipEntry
from contracts.tool import ToolParamsRequest
from infrastructure.agent_prompt import normalize_imported_agent_bundle
from nexent.core.agents.agent_model import AgentVerificationConfig, ToolConfig
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)


@dataclass(frozen=True)
class AgentModelProjection:
    """Public model fields plus private availability metadata."""

    fields: dict
    deleted_model_ids: frozenset[int]
    availability_model_ids: list[int]


@dataclass(frozen=True)
class AgentRunContext:
    metadata: Any
    enable_memory: bool


@dataclass(frozen=True)
class SystemAgentRef:
    """Immutable reference to one published system Agent snapshot."""

    tenant_id: str
    system_key: str
    agent_id: int
    version_no: int


@dataclass(frozen=True)
class WorkbenchReleaseManifest:
    """Server-controlled capabilities for one Nexent release."""

    system_revision: str
    persistent_tool_names: tuple[str, ...]
    official_skill_names: tuple[str, ...] = WORKBENCH_OFFICIAL_SKILL_NAMES


@dataclass
class OptimizeRequest:
    """优化请求的统一数据结构"""

    agent_id: int
    model_id: int
    task_description: str
    section_type: str
    section_title: str
    current_content: str
    feedback: str
    mode: str = "general"
    start_pos: Opt[int] = None
    end_pos: Opt[int] = None
    tool_ids: Opt[list[int]] = None
    sub_agent_ids: Opt[list[int]] = None
    knowledge_base_display_names: Opt[list[str]] = None


@dataclass
class OptimizeResult:
    """优化结果的统一数据结构"""

    optimized_content: str
    source: str
    section_type: str = ""
    section_title: str = ""
    original_content: str = ""


def _validated_context_policy(
    value: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Validate a partial request/agent policy while preserving its layer shape."""
    if value is None:
        return None
    from nexent.core.agents.context import PolicyLayers, resolve_policy

    resolve_policy(PolicyLayers(request=value))
    return value


class RuntimeAgentMount(BaseModel):
    """Stable reference to one Agent version selected by the Workbench."""

    model_config = ConfigDict(extra="forbid")

    agent_id: int = Field(gt=0)
    version_no: Optional[int] = Field(default=None, gt=0)


class RuntimeSkillMount(BaseModel):
    """Complete root-Agent Skill selection for a Workbench conversation."""

    model_config = ConfigDict(extra="forbid")

    skill_id: int = Field(gt=0)
    config_values: Dict[str, Any] = Field(default_factory=dict)




class WorkbenchSessionConfig(BaseModel):
    """Canonical, persisted Workbench declaration; resolved artifacts are excluded."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[4] = 4
    mode: WorkbenchMode
    requested_output_tokens: Optional[int] = Field(default=None, gt=0)
    agent_mounts: List[RuntimeAgentMount] = Field(default_factory=list, max_length=8)
    skill_mounts: List[RuntimeSkillMount] = Field(default_factory=list, max_length=20)
    knowledge_scope: Optional[ConversationKnowledgeScopeRequest] = None

    @model_validator(mode="after")
    def validate_mode_resources(self):
        agent_count = len(self.agent_mounts)
        if self.mode == "generic_chat" and agent_count != 0:
            raise ValueError("generic_chat does not accept Agent mounts")
        if self.mode == "single_agent_chat" and agent_count != 1:
            raise ValueError("single_agent_chat requires exactly one Agent mount")
        if self.mode == "multi_agent_chat" and agent_count < 2:
            raise ValueError("multi_agent_chat requires at least two Agent mounts")
        if self.mode in {"skill_create", "agent_create"}:
            if agent_count or self.skill_mounts or self.knowledge_scope is not None:
                raise ValueError(
                    "creation modes do not accept Agent, Skill, or knowledge resources"
                )
        skill_ids = [mount.skill_id for mount in self.skill_mounts]
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError("skill_mounts contains duplicate skill_id values")
        agent_keys = [(mount.agent_id, mount.version_no) for mount in self.agent_mounts]
        if len(agent_keys) != len(set(agent_keys)):
            raise ValueError("agent_mounts contains duplicate Agent references")
        return self


class WorkbenchConfigUpdateRequest(BaseModel):
    """Optimistic-lock replacement request for an existing conversation."""

    model_config = ConfigDict(extra="forbid")

    config: WorkbenchSessionConfig
    expected_version: int = Field(ge=0)


class WorkbenchCapabilityPreviewRequest(BaseModel):
    """Request defaults and capabilities for one candidate published Agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: int = Field(gt=0)
    version_no: Optional[int] = Field(default=None, gt=0)


def reject_legacy_agent_fields(value):
    """Reject removed execution controls rather than silently starting a new run."""
    if isinstance(value, dict) and {
        "enable_hitl",
        "hitl_run_id",
        "hitl_after_event",
    }.intersection(value):
        raise ValueError(
            "Legacy human interaction fields are no longer supported; send a normal query"
        )
    return value


class AgentRequest(BaseModel):
    # Internal provenance is never accepted from serialized client requests.
    _message_source: str = PrivateAttr(default="CHAT")
    query: str
    clarification_response: Optional[ClarificationResponse] = None
    conversation_id: Optional[int] = None
    history: Optional[List[HistoryItem]] = None
    # Complete list of attachment information
    minio_files: Optional[List[Dict[str, Any]]] = None
    agent_id: Optional[int] = None
    model_id: Optional[StrictInt] = Field(default=None, gt=0)
    model_parameter_preferences: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    requested_output_tokens: Optional[int] = Field(default=None, gt=0)
    version_no: Optional[int] = None
    is_debug: Optional[bool] = False
    tool_params: Optional[ToolParamsRequest] = None
    knowledge_scope: Optional[ConversationKnowledgeScopeRequest] = None
    entrypoint: Optional[Literal["workbench"]] = None
    workbench: Optional[WorkbenchSessionConfig] = None
    expected_workbench_config_version: Optional[int] = Field(default=None, ge=0)
    context_policy: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional request-scoped context policy override",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Conversation runtime metadata available to the agent",
    )
    expected_metadata_version: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional optimistic-lock version for runtime metadata updates",
    )

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_execution_controls(cls, value):
        return reject_temporary_model_controls(reject_legacy_agent_fields(value))

    @field_validator("context_policy")
    @classmethod
    def validate_context_policy(cls, value):
        return _validated_context_policy(value)

    @model_validator(mode="after")
    def validate_workbench_entrypoint(self):
        if (
            self.entrypoint == "workbench"
            and self.workbench is None
            and self.conversation_id is None
        ):
            raise ValueError("workbench entrypoint requires a Workbench configuration")
        if self.workbench is not None and self.entrypoint != "workbench":
            raise ValueError("Workbench configuration requires entrypoint='workbench'")
        return self

    enable_plan: Optional[bool] = Field(
        default=False,
        description="Whether to enable the planning phase before execution",
    )
    enable_automation_tool: bool = Field(
        default=True,
        description="Whether the root interactive Agent may create scheduled-task proposals",
    )




class NL2ModelControlsRequest(BaseModel):
    """The same per-model preferences used by every Agent conversation."""

    model_id: Optional[StrictInt] = Field(default=None, gt=0)
    model_parameter_preferences: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def reject_removed_controls(cls, value):
        return reject_temporary_model_controls(value)


class NL2AgentRunRequest(NL2ModelControlsRequest):
    """Request payload for an NL2Agent turn, optionally persisted by Workbench."""

    query: str = Field(min_length=1)
    history: Optional[List[HistoryItem]] = None
    minio_files: Optional[List[Dict[str, Any]]] = None
    agent_id: int = Field(gt=0)
    conversation_id: Optional[int] = Field(default=None, gt=0)
    retry_user_message_id: Optional[int] = Field(default=None, gt=0)
    retry_message_index: Optional[int] = Field(default=None, ge=0)
    persist_history: bool = False
    workbench_config: Optional[Dict[str, Any]] = None


class NL2SkillRunRequest(NL2ModelControlsRequest):
    """Request payload for an NL2Skill turn, optionally persisted by Workbench."""

    query: str = Field(min_length=1)
    history: Optional[List[HistoryItem]] = None
    minio_files: Optional[List[Dict[str, Any]]] = None
    conversation_id: Optional[int] = Field(default=None, gt=0)
    retry_user_message_id: Optional[int] = Field(default=None, gt=0)
    retry_message_index: Optional[int] = Field(default=None, ge=0)
    persist_history: bool = False
    workbench_config: Optional[Dict[str, Any]] = None
    draft_snapshot: Optional[Dict[str, Any]] = None
    language: Optional[Literal["zh", "en"]] = None




class OptimizePromptSectionRequest(BaseModel):
    task_description: str
    agent_id: int
    model_id: int
    section_type: str
    section_title: str
    current_content: str
    feedback: str
    mode: Literal["general", "insert", "select"] = "general"
    start_pos: Optional[int] = Field(
        None, description="Start position for insert/select mode"
    )
    end_pos: Optional[int] = Field(
        None, description="End position for insert/select mode"
    )
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


class AgentSkillInstanceRequest(BaseModel):
    """Skill selection and per-agent configuration saved with an agent."""

    skill_id: int
    enabled: bool = True
    config_values: Dict[str, Any] = Field(default_factory=dict)


# used in agent/search agent/update for save agent info
class RelatedAgentInfo(BaseModel):
    """Related agent info with pinned version."""

    agent_id: int
    version_no: Optional[int] = None


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
    prompt: Optional[str] = None
    enabled: Optional[bool] = None
    business_logic_model_name: Optional[str] = None
    business_logic_model_id: Optional[int] = None
    enabled_tool_ids: Optional[List[int]] = None
    enabled_skill_ids: Optional[List[int]] = None
    skill_instances: Optional[List[AgentSkillInstanceRequest]] = None
    related_agent_ids: Optional[List[int]] = None
    related_agents: Optional[List[RelatedAgentInfo]] = None  # Related agents with pinned versions
    related_external_agent_ids: Optional[List[int]] = None
    group_ids: Optional[List[int]] = None
    ingroup_permission: Optional[str] = None
    enable_context_manager: Optional[bool] = None
    enable_protocol_repair_retry: Optional[bool] = None
    is_a2a: Optional[bool] = None
    verification_config: Optional[Dict[str, Any]] = None
    context_policy: Optional[Dict[str, Any]] = None
    # v2.6.0 per-agent model inference param overrides.
    # Shape: {"<model_id>": {"temperature": 0.5, "top_p": null, "extra_params": {...}}}.
    # NULL means inherit model defaults.
    model_params_override: Optional[Dict[str, Any]] = None
    allow_chat_metadata: Optional[bool] = None

    greeting_message: Optional[str] = None
    example_questions: Optional[List[str]] = None
    icon_url: Optional[str] = None
    version_no: int = 0

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        # Imported lazily: contracts must not require the SDK package at import
        # time, because several unit suites stub ``nexent.core`` wholesale.
        from nexent.core.agent_names import validate_agent_name

        return validate_agent_name(value)

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


class ExportAndImportAgentInfo(BaseModel):
    agent_id: int
    tenant_id: Optional[str] = None
    name: str
    display_name: Optional[str] = None
    description: str
    author: Optional[str] = None
    max_steps: int
    requested_output_tokens: Optional[int] = Field(default=None, gt=0)
    is_main_agent: bool = True
    provide_run_summary: bool
    allow_chat_metadata: bool = False
    enable_protocol_repair_retry: bool = False
    verification_config: Optional[Dict[str, Any]] = None
    context_policy: Optional[Dict[str, Any]] = None
    prompt: Optional[str] = None
    enabled: bool
    tools: List[ToolConfig]
    managed_agents: List[int]
    model_ids: Optional[List[int]] = None
    model_names: Optional[List[str]] = None
    business_logic_model_id: Optional[int] = None
    business_logic_model_name: Optional[str] = None
    skill_names: Optional[List[str]] = None
    # v2.6.0 per-agent model inference param overrides (mirrors AgentInfo column).
    model_params_override: Optional[Dict[str, Any]] = None
    greeting_message: Optional[str] = None
    example_questions: Optional[List[str]] = None

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


# ---------------------------------------------------------------------------
# Official agent bundles (platform-provided, mirroring official skills)
# ---------------------------------------------------------------------------


class KnowledgeBaseSeedDoc(BaseModel):
    """A seed document in an official agent bundle's knowledge base.

    Text seeds carry ``content``; binary seeds (docx/pdf/...) carry ``file_path``
    pointing at the real file on disk (set by the loader for directory layouts,
    so the install pipeline can upload it like a normal KB document). At least
    one of the two is set.
    """

    file_name: str
    content: Optional[str] = None
    file_path: Optional[str] = None


class KnowledgeBaseSeed(BaseModel):
    """Knowledge base declaration inside an official agent bundle.

    ``logical_index_name`` is the bundle-local reference that agent tools point
    to; it is remapped to the tenant's real generated index name on install.
    """

    logical_index_name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    documents: List[KnowledgeBaseSeedDoc] = []


class OfficialAgentBundle(AgentRepositorySnapshot):
    """Official agent bundle: marketplace snapshot plus official card fields.

    Reuses AgentRepositorySnapshot (agent_info / mcp_info / skills) and adds
    official card metadata plus optional knowledge base seed documents.
    An empty ``knowledge_bases`` list means the agent has no KB dependency.

    Card fields are optional: when omitted they are derived from the root agent
    (name / display_name) or sensible defaults (icon, version_label), so a bare
    export can be used directly as a bundle without manual card editing.
    """

    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    tags: List[str] = []
    version_label: Optional[str] = None
    knowledge_bases: List[KnowledgeBaseSeed] = []

    @model_validator(mode="after")
    def _derive_card_fields(self) -> "OfficialAgentBundle":
        root_agent = self.agent_info.get(str(self.agent_id))
        root_name = getattr(root_agent, "name", None) if root_agent else None
        root_display_name = (
            getattr(root_agent, "display_name", None) if root_agent else None
        )
        if not self.name:
            self.name = root_name or "agent"
        if not self.display_name:
            self.display_name = root_display_name or self.name
        if not self.icon:
            self.icon = "🤖"
        if not self.version_label:
            self.version_label = "V1"
        return self


OfficialAgentStatus = Literal["installed", "needs_model", "installable"]


class OfficialAgentAgentInfo(BaseModel):
    """An agent inside an official bundle (root or sub-agent) for conflict pre-check."""

    name: str
    display_name: Optional[str] = None


class OfficialAgentMcpPreview(BaseModel):
    """MCP server declaration inside an official bundle, with per-tenant install state."""

    mcp_server_name: str
    mcp_url: str
    installed: bool = False


class OfficialAgentListItem(BaseModel):
    """Single item in the GET /repository/agent/official response."""

    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    tags: List[str] = []
    version_label: Optional[str] = None
    status: OfficialAgentStatus
    has_knowledge: bool
    mcp_count: int
    skill_count: int
    kb_count: int
    missing_models: List[str] = []
    agents: List[OfficialAgentAgentInfo] = []
    mcps: List[OfficialAgentMcpPreview] = []


OfficialAgentInstallStatus = Literal[
    "installed", "needs_model", "already_installed", "not_found", "failed"
]

OfficialAgentInstallStepStatus = Literal["ok", "failed"]


class OfficialAgentInstallStep(BaseModel):
    """One step of an official agent install (mcp / tools / knowledge_base / agent).

    ``status`` is "ok" when the step completed, "failed" when it raised (the
    install aborts and the failed step's message explains why).
    """

    name: str
    status: OfficialAgentInstallStepStatus
    message: Optional[str] = None


class OfficialAgentInstallRequest(BaseModel):
    """Request body for installing official agents.

    ``renames`` maps an existing agent name inside a bundle to a new name
    (used to resolve name conflicts before import). ``model_ids`` maps a bundle
    key to a tenant LLM model_id applied to the bundle's root agent on install.
    """

    agent_names: List[str] = Field(
        ..., min_length=1, description="Official agent bundle names to install"
    )
    renames: Optional[Dict[str, str]] = None
    model_ids: Optional[Dict[str, int]] = None
    embedding_model_ids: Optional[Dict[str, int]] = None


class OfficialAgentInstallItem(BaseModel):
    """Per-agent result of an official agent install request."""

    name: str
    status: OfficialAgentInstallStatus
    message: Optional[str] = None
    steps: Optional[List[OfficialAgentInstallStep]] = None
    missing_models: List[str] = []
    agent_id: Optional[int] = None


class OfficialAgentInstallResponse(BaseModel):
    """Response payload for POST /repository/agent/official/install."""

    results: List[OfficialAgentInstallItem]


RepositoryImportRequirementType = Literal[
    "model", "knowledge_base", "mcp", "skill", "tool"
]


class RepositoryImportRequirementItem(BaseModel):
    """Single dependency item for repository import precheck."""

    type: RepositoryImportRequirementType
    key: str
    name: str
    description: Optional[str] = None
    available: bool
    reason_code: Optional[str] = None
    suggested_new_name: Optional[str] = None
    resolution_required: bool = False
    existing_index_name: Optional[str] = None


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

    icon_url: Optional[str] = Field(None, description="Repository icon URL")
    downloads: int = Field(
        0, ge=0, description="Initial download/copy count for card display"
    )
    tags: Optional[List[str]] = Field(None, description="Marketplace tags")
    tool_count: Optional[int] = Field(
        None, ge=0, description="Total tool count across all agents in the bundle"
    )
    content: Optional[str] = Field(
        None, description="Listing note when submitting for review"
    )


class AgentRepositoryListingDetailResponse(BaseModel):
    """Detailed marketplace listing payload for repository detail view."""
    agent_repository_id: int
    agent_id: Optional[int] = None
    version_no: Optional[int] = None
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    icon_url: Optional[str] = None
    status: str
    version_label: Optional[str] = None
    downloads: int = 0
    created_at: Optional[str] = None
    model_name: Optional[str] = None
    prompt: Optional[str] = None
    tools: List[str] = Field(default_factory=list)


class SkillConflictCheckRequest(BaseModel):
    """Skill names to check before showing the agent import steps."""

    skill_names: List[str]


class AgentImportRequest(BaseModel):
    @field_validator("agent_info", mode="before")
    @classmethod
    def normalize_external_prompt_fields(cls, values):
        return normalize_imported_agent_bundle(values)

    agent_info: ExportAndImportDataFormat
    force_import: bool = False
    skills: Optional[List[SkillZipEntry]] = None
    skill_resolutions: Optional[List[SkillResolution]] = None


class AgentNameBatchRegenerateItem(BaseModel):
    name: str
    display_name: Optional[str] = None
    task_description: Optional[str] = ""
    agent_id: Optional[int] = None


class AgentNameBatchRegenerateRequest(BaseModel):
    items: List[AgentNameBatchRegenerateItem]


class AgentNameBatchCheckItem(BaseModel):
    name: str = ""
    display_name: Optional[str] = None
    agent_id: Optional[int] = None


class AgentNameBatchCheckRequest(BaseModel):
    items: List[AgentNameBatchCheckItem]


class ConvertStateRequest(BaseModel):
    """Request schema for /tasks/convert_state endpoint"""

    process_state: str = ""
    forward_state: str = ""


# Agent Version Management Data Models
# ---------------------------------------------------------------------------
class VersionPublishRequest(BaseModel):
    """Request model for publishing a new version"""

    version_name: Optional[str] = Field(
        None, description="User-defined version name for display"
    )
    release_note: Optional[str] = Field(
        None, description="Release notes / publish remarks"
    )


class VersionListItemResponse(BaseModel):
    """Response model for version list item"""

    id: int = Field(..., description="Version record ID")
    version_no: int = Field(..., description="Version number")
    version_name: Optional[str] = Field(None, description="User-defined version name")
    release_note: Optional[str] = Field(None, description="Release notes")
    source_version_no: Optional[int] = Field(
        None, description="Source version number if rollback"
    )
    source_type: Optional[str] = Field(
        None, description="Source type: NORMAL / ROLLBACK"
    )
    status: str = Field(
        ..., description="Version status: RELEASED / DISABLED / ARCHIVED"
    )
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
    created_by: str = Field(..., description="User who published this version")
    create_time: Optional[str] = Field(None, description="Publish timestamp")
    agent_info: Optional[dict] = Field(None, description="Agent info snapshot")
    tool_instances: List[dict] = Field(
        default_factory=list, description="Tool instance snapshots"
    )
    relations: List[dict] = Field(
        default_factory=list, description="Relation snapshots"
    )


class VersionRollbackRequest(BaseModel):
    """Request model for rollback to a specific version"""

    version_name: Optional[str] = Field(
        None, description="New version name for the rollback version"
    )
    release_note: Optional[str] = Field(
        None, description="Release notes for the rollback version"
    )


class VersionStatusRequest(BaseModel):
    """Request model for updating version status"""

    status: str = Field(..., description="New status: DISABLED / ARCHIVED")


class VersionUpdateRequest(BaseModel):
    """Request model for updating version metadata (name and description)"""

    version_name: Optional[str] = Field(
        None, description="User-defined version name for display"
    )
    release_note: Optional[str] = Field(
        None, description="Release notes / version description"
    )


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


# Agent Unavailable Reason Constants
#
# Centralized definition of all possible reasons why an agent may be unavailable.
# These values are returned to the frontend via the 'unavailable_reasons' field.
class AgentUnavailableReason:
    """Reason codes for agent unavailability."""

    # Identity conflicts
    DUPLICATE_NAME = "duplicate_name"
    DUPLICATE_DISPLAY_NAME = "duplicate_display_name"

    # Model issues
    MODEL_NOT_CONFIGURED = "model_not_configured"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_DELETED = "model_deleted"

    # Tool issues
    TOOL_UNAVAILABLE = "tool_unavailable"
    ALL_TOOLS_DISABLED = "all_tools_disabled"
    MCP_MODEL_UNAVAILABLE = "mcp_model_unavailable"

    # Agent issues
    AGENT_NOT_FOUND = "agent_not_found"

    @classmethod
    def all_reasons(cls) -> list[str]:
        """Return all defined unavailable reason codes."""
        return [
            cls.DUPLICATE_NAME,
            cls.DUPLICATE_DISPLAY_NAME,
            cls.MODEL_NOT_CONFIGURED,
            cls.MODEL_UNAVAILABLE,
            cls.MODEL_DELETED,
            cls.TOOL_UNAVAILABLE,
            cls.ALL_TOOLS_DISABLED,
            cls.AGENT_NOT_FOUND,
            cls.MCP_MODEL_UNAVAILABLE,
        ]

    @classmethod
    def is_valid_reason(cls, reason: str) -> bool:
        """Check if a reason string is a valid reason code."""
        return reason in cls.all_reasons()


def reject_temporary_model_controls(value):
    """Reject the removed parallel contract instead of silently dropping intent."""
    if isinstance(value, dict) and {"generation_config", "reasoning_effort", "reasoning_budget_tokens"}.intersection(value):
        raise ValueError("Use model_parameter_preferences for conversation model parameters")
    if (isinstance(value, dict) and value.get("conversation_id") is not None
            and value.get("model_parameter_preferences") and value.get("is_debug") is not True):
        raise ValueError("Save existing conversation parameters through the preference endpoint")
    return value
