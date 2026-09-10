"""Define and implement the internal Local MCP tools used by NL2Agent."""

import json
import logging
import re
import unicodedata
from typing import Any, Literal

from fastmcp.server.dependencies import get_http_request
from nexent.core.agents.agent_model import ToolConfig
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from consts.exceptions import UnauthorizedError
from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)

NL2A_MCP_SERVICE_NAME = "nl2a"
SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME = "search_installed_mcp_tools"
SEARCH_INSTALLED_RESOURCES_LOCAL_NAME = "search_installed_resources"
SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME = "search_uninstalled_resources"
RECOMMEND_RESOURCES_LOCAL_NAME = "recommend_resources"
RESOLVE_RESOURCE_REQUIREMENTS_LOCAL_NAME = "resolve_resource_requirements"
SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME = "save_agent_draft_fields"
NL2A_WRAPPER_LOCAL_NAME = "wrapper"
NL2A_MCP_LOCAL_TOOL_NAMES = (
    SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME,
    SEARCH_INSTALLED_RESOURCES_LOCAL_NAME,
    SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME,
    RECOMMEND_RESOURCES_LOCAL_NAME,
    RESOLVE_RESOURCE_REQUIREMENTS_LOCAL_NAME,
    SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME,
    NL2A_WRAPPER_LOCAL_NAME,
)
(
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SEARCH_UNINSTALLED_RESOURCES_NAME,
    RECOMMEND_RESOURCES_NAME,
    RESOLVE_RESOURCE_REQUIREMENTS_NAME,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    NL2A_WRAPPER_NAME,
) = tuple(
    f"{NL2A_MCP_SERVICE_NAME}_{name}"
    for name in NL2A_MCP_LOCAL_TOOL_NAMES
)
NL2A_MCP_TOOL_NAMES = (
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SEARCH_UNINSTALLED_RESOURCES_NAME,
    RECOMMEND_RESOURCES_NAME,
    RESOLVE_RESOURCE_REQUIREMENTS_NAME,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    NL2A_WRAPPER_NAME,
)
NL2A_MCP_LEGACY_TOOL_NAMES = (
    SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME,
    SEARCH_INSTALLED_RESOURCES_LOCAL_NAME,
    SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME,
    RECOMMEND_RESOURCES_LOCAL_NAME,
    RESOLVE_RESOURCE_REQUIREMENTS_LOCAL_NAME,
    SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME,
    NL2A_WRAPPER_NAME,
)
NL2AGENT_AGENT_ID_HEADER = "X-Nexent-NL2Agent-Agent-ID"
SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION = (
    "Search the current tenant's installed and available MCP tools using keywords. "
    "Returns JSON text ordered by relevance. Decode the result with json.loads "
    f"before passing it to {NL2A_WRAPPER_NAME}, preserve the decoded content unchanged, "
    "and use print(result) to expose the decoded observation."
)
SEARCH_INSTALLED_RESOURCES_DESCRIPTION = (
    "Search all current-user-visible installed Local Tools, MCP Tools, and Skills "
    "for a structured set of capability requirements. Return no more than 12 "
    "ranked candidates as JSON text. Decode the result with json.loads before "
    "indexing it, and preserve the decoded candidates unchanged when calling "
    f"{RECOMMEND_RESOURCES_NAME}."
)
SEARCH_UNINSTALLED_RESOURCES_DESCRIPTION = (
    "Search installable Nexent Skills and tenant Skill/MCP repositories for "
    "structured capability requirements. Pass skipped candidate_ref values "
    "unchanged in exclude_refs, and preserve returned candidates unchanged when "
    f"calling {RECOMMEND_RESOURCES_NAME}."
)
RECOMMEND_RESOURCES_DESCRIPTION = (
    "Resolve installed or installable resource candidates into verified card "
    "details. Pass unchanged candidates returned by resource searches and a "
    "unique recommended_refs subset. Decode the JSON result, then pass it "
    f"unchanged to {NL2A_WRAPPER_NAME} with the matching installation or binding subtype."
)
RESOLVE_RESOURCE_REQUIREMENTS_DESCRIPTION = (
    "Resolve every structured capability requirement against installed and "
    "installable resources. With verification_required=true, first returns a "
    "finite backend-ranked candidate set and next_action=VERIFY. Submit one "
    "capability_verifications verdict for each strong candidate, then call this "
    "tool again without verification_required. The final result contains "
    "backend-owned per-requirement states (`covered`, `installable`, or "
    "`uncovered`) and exactly one card next_action. Never invent candidate_ref "
    "values or capabilities not present in the supplied resource summary."
)
NL2A_WRAPPER_DESCRIPTION = (
    "Build one NL2Agent output for the existing draft. Always pass the current "
    "`agent_id` and `subtype`. For `requirement_clarification`, pass structured "
    "`questions`. For resource installation or binding, pass `agent_id` and the "
    "verified `resource_result` returned by the unified resolver. JSON parameters "
    "must be decoded dictionaries, "
    f"never raw JSON strings. Call the tool as `result = {NL2A_WRAPPER_NAME}(...)`, "
    "then use `print(result)`."
)
SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION = (
    "Partially update the current tenant's existing ordinary agent draft. "
    "Always pass the current agent_id and only whitelisted description or Prompt "
    "fields, never null. Never update name or display_name. Call the tool as "
    f"`result = {SAVE_AGENT_DRAFT_FIELDS_NAME}(...)`, then use `print(result)` exactly once."
)
NL2AGENT_MCP_TOOL_META = {"nexent_internal": True}
MAX_BINDING_CANDIDATES = 12
MAX_REQUIREMENT_CLARIFICATION_QUESTIONS = 5
_NL2AGENT_PROMPT_FIELDS = frozenset(
    {
        "duty_prompt",
        "constraint_prompt",
        "few_shots_prompt",
        "greeting_message",
        "example_questions",
    }
)
_NL2AGENT_FINAL_PROMPT_BATCH = frozenset({"greeting_message", "example_questions"})
_NL2AGENT_DRAFT_SYNC_FIELDS = frozenset(
    {"description", *_NL2AGENT_PROMPT_FIELDS}
)
NL2A_SUBTYPES = Literal[
    "requirement_clarification",
    "suggested_resource_installation",
    "installed_resource_binding",
    "resource_gap_resolution",
]

INSTALLED_RESOURCE_SOURCES = frozenset(
    {"LOCAL_TOOL", "MCP_TOOL", "INSTALLED_SKILL"}
)
UNINSTALLED_RESOURCE_SOURCES = frozenset(
    {
        "NEXENT_OFFICIAL_SKILL",
        "TENANT_SKILL_REPOSITORY",
        "TENANT_MCP_REPOSITORY",
    }
)


class ResourceRequirement(BaseModel):
    """One capability requirement shared by the phase-two search tools."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    requirement_id: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=500)
    resource_name_hint: str | None = Field(default=None, max_length=200)
    search_terms: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_search_terms(self) -> "ResourceRequirement":
        normalized = [
            unicodedata.normalize("NFKC", term).casefold().strip()
            for term in self.search_terms
        ]
        if any(not term for term in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("search_terms must be non-empty and unique")
        return self


class ResourceCandidate(BaseModel):
    """Frozen common output boundary for resource discovery."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_ref: str = Field(min_length=1)
    resource_type: Literal["tool", "skill", "mcp_server"]
    source: Literal[
        "LOCAL_TOOL",
        "MCP_TOOL",
        "INSTALLED_SKILL",
        "NEXENT_OFFICIAL_SKILL",
        "TENANT_SKILL_REPOSITORY",
        "TENANT_MCP_REPOSITORY",
    ]
    name: str = Field(min_length=1)
    description: str = ""
    requirement_ids: list[str] = Field(min_length=1)
    score: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_requirement_ids(self) -> "ResourceCandidate":
        if len(self.requirement_ids) != len(set(self.requirement_ids)):
            raise ValueError("requirement_ids must be unique")
        return self


class SearchInstalledResourcesInput(BaseModel):
    """Frozen input for installed Tool/Skill discovery (implemented in PR2)."""

    model_config = ConfigDict(extra="forbid")
    requirements: list[ResourceRequirement] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_requirement_ids(self) -> "SearchInstalledResourcesInput":
        requirement_ids = [item.requirement_id for item in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirement_id values must be unique")
        return self


class SearchUninstalledResourcesInput(BaseModel):
    """Frozen input for tenant-visible installable resource discovery."""

    model_config = ConfigDict(extra="forbid")
    requirements: list[ResourceRequirement] = Field(min_length=1, max_length=8)
    exclude_refs: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_identifiers(self) -> "SearchUninstalledResourcesInput":
        requirement_ids = [item.requirement_id for item in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirement_id values must be unique")
        if (
            len(self.exclude_refs) != len(set(self.exclude_refs))
            or any(not ref.strip() for ref in self.exclude_refs)
        ):
            raise ValueError("exclude_refs must be non-empty and unique")
        return self


class ResourceSearchOutput(BaseModel):
    """Frozen successful output shared by both resource search tools."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["success"] = "success"
    candidates: list[ResourceCandidate]
    uncovered_requirement_ids: list[str]
    matches_by_requirement: dict[str, list["ResourceMatch"]] = Field(
        default_factory=dict
    )


ResourceResolutionPhase = Literal["INITIAL", "POST_INSTALL", "POST_GAP"]
ResourceResolutionState = Literal["covered", "installable", "uncovered"]
ResourceResolutionNextAction = Literal[
    "VERIFY", "INSTALL", "RESOLVE_GAP", "BIND"
]


class ResolveResourceRequirementsInput(SearchUninstalledResourcesInput):
    """Validated input for the unified backend-owned resource resolver."""

    phase: ResourceResolutionPhase
    verification_required: bool = False
    capability_verifications: list["CapabilityVerification"] | None = None


class ResourceMatch(BaseModel):
    """One backend-computed requirement-to-resource relationship."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_ref: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    strength: Literal["strong", "weak"]

    @model_validator(mode="after")
    def validate_strength(self) -> "ResourceMatch":
        if self.strength == "strong" and self.score < 0.65:
            raise ValueError("strong matches require score >= 0.65")
        if self.strength == "weak" and not 0.50 <= self.score < 0.65:
            raise ValueError("weak matches require 0.50 <= score < 0.65")
        return self


class CapabilityVerification(BaseModel):
    """Model verdict for one backend-supplied requirement/candidate pair."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    requirement_id: str = Field(min_length=1)
    candidate_ref: str = Field(min_length=1)
    decision: Literal["accept", "reference", "reject"]
    reason: str = Field(min_length=1, max_length=500)
    missing_capabilities: list[str] = Field(default_factory=list, max_length=8)


class ResourceCardSummary(BaseModel):
    """Configuration-free resource metadata safe for NL2Agent cards."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_ref: str = Field(min_length=1)
    resource_type: Literal["tool", "skill", "mcp_server"]
    source: Literal[
        "LOCAL_TOOL",
        "MCP_TOOL",
        "INSTALLED_SKILL",
        "NEXENT_OFFICIAL_SKILL",
        "TENANT_SKILL_REPOSITORY",
        "TENANT_MCP_REPOSITORY",
    ]
    name: str = Field(min_length=1)
    description: str = ""
    requirement_ids: list[str] = Field(min_length=1, max_length=8)
    recommendation: Literal["recommended", "optional"]
    is_bound: bool = False

    @model_validator(mode="after")
    def validate_requirement_ids(self) -> "ResourceCardSummary":
        if len(self.requirement_ids) != len(set(self.requirement_ids)):
            raise ValueError("requirement_ids must be unique")
        return self


class RequirementResolution(BaseModel):
    """Backend-owned state for one resource requirement."""

    model_config = ConfigDict(extra="forbid")

    requirement: ResourceRequirement
    state: ResourceResolutionState
    installed_matches: list[ResourceMatch] = Field(default_factory=list)
    installable_matches: list[ResourceMatch] = Field(default_factory=list)
    weak_references: list[ResourceMatch] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def validate_matches(self) -> "RequirementResolution":
        if any(match.strength != "strong" for match in self.installed_matches):
            raise ValueError("installed_matches must contain strong matches")
        if any(match.strength != "strong" for match in self.installable_matches):
            raise ValueError("installable_matches must contain strong matches")
        if any(match.strength != "weak" for match in self.weak_references):
            raise ValueError("weak_references must contain weak matches")
        for matches in (
            self.installed_matches,
            self.installable_matches,
            self.weak_references,
        ):
            refs = [match.candidate_ref for match in matches]
            if len(refs) != len(set(refs)):
                raise ValueError("match candidate_ref values must be unique")
        expected_state = (
            "covered"
            if self.installed_matches
            else "installable"
            if self.installable_matches
            else "uncovered"
        )
        if self.state != expected_state:
            raise ValueError(
                f"state must be {expected_state} for the available strong matches"
            )
        return self


class ResourceResolutionOutput(BaseModel):
    """Complete backend resolution for one NL2Agent resource phase."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success"] = "success"
    phase: ResourceResolutionPhase
    verification_required: bool = False
    next_action: ResourceResolutionNextAction
    requirements: list[RequirementResolution]
    resources: list[ResourceCardSummary]

    @model_validator(mode="after")
    def validate_resolution(self) -> "ResourceResolutionOutput":
        requirement_ids = [
            item.requirement.requirement_id for item in self.requirements
        ]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirement_id values must be unique")
        resource_refs = [item.candidate_ref for item in self.resources]
        if len(resource_refs) != len(set(resource_refs)):
            raise ValueError("resource candidate_ref values must be unique")
        states = {item.state for item in self.requirements}
        if self.phase != "INITIAL" and "installable" in states:
            raise ValueError("post-install phases cannot contain installable state")
        expected_action = (
            "VERIFY"
            if self.verification_required
            else "INSTALL"
            if self.phase == "INITIAL" and "installable" in states
            else "RESOLVE_GAP"
            if "uncovered" in states
            else "BIND"
        )
        if self.next_action != expected_action:
            raise ValueError(
                f"next_action must be {expected_action} for the resolved states"
            )
        return self


class WeakResourceReference(BaseModel):
    """Display-only weak candidate shown on a resource-gap card."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_ref: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    source: Literal[
        "LOCAL_TOOL",
        "MCP_TOOL",
        "INSTALLED_SKILL",
        "NEXENT_OFFICIAL_SKILL",
        "TENANT_SKILL_REPOSITORY",
        "TENANT_MCP_REPOSITORY",
    ]
    score: float = Field(ge=0.50, lt=0.65)


class ResourceGapRequirement(BaseModel):
    """One uncovered requirement and its optional weak references."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    requirement_id: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=500)
    search_terms: list[str] = Field(default_factory=list, max_length=8)
    weak_references: list[WeakResourceReference] = Field(
        default_factory=list, max_length=2
    )


class SuggestedResourceInstallationPayloadV2(BaseModel):
    """Configuration-free resource installation card payload."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    subtype: Literal["suggested_resource_installation"] = (
        "suggested_resource_installation"
    )
    agent_id: int = Field(gt=0)
    resources: list[ResourceCardSummary] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_installable_sources(
        self,
    ) -> "SuggestedResourceInstallationPayloadV2":
        if any(
            resource.source not in UNINSTALLED_RESOURCE_SOURCES
            for resource in self.resources
        ):
            raise ValueError("installation resources must be installable")
        return self


class InstalledResourceBindingPayloadV2(BaseModel):
    """Configuration-free installed resource binding card payload."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    subtype: Literal["installed_resource_binding"] = "installed_resource_binding"
    agent_id: int = Field(gt=0)
    resources: list[ResourceCardSummary] = Field(max_length=12)
    requirements: list[ResourceRequirement] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_installed_sources(self) -> "InstalledResourceBindingPayloadV2":
        if any(
            resource.source not in INSTALLED_RESOURCE_SOURCES
            for resource in self.resources
        ):
            raise ValueError("binding resources must already be installed")
        requirement_ids = [item.requirement_id for item in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirement_id values must be unique")
        return self


class ResourceGapResolutionPayloadV2(BaseModel):
    """Configuration-free resource gap card payload."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    subtype: Literal["resource_gap_resolution"] = "resource_gap_resolution"
    agent_id: int = Field(gt=0)
    requirements: list[ResourceGapRequirement] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_requirement_ids(self) -> "ResourceGapResolutionPayloadV2":
        requirement_ids = [item.requirement_id for item in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirement_id values must be unique")
        return self


def get_resource_gap_requirements(
    *,
    requirements: list[ResourceRequirement],
    installed: ResourceSearchOutput,
    installable: ResourceSearchOutput,
) -> list[ResourceRequirement]:
    """Return requirements not covered by installed or installable resources."""

    uncovered_by_both = set(installed.uncovered_requirement_ids) & set(
        installable.uncovered_requirement_ids
    )
    return [
        requirement
        for requirement in requirements
        if requirement.requirement_id in uncovered_by_both
    ]


class RecommendResourcesInput(BaseModel):
    """Frozen input for resolving selected candidates into card data (PR2)."""

    model_config = ConfigDict(extra="forbid")
    candidates: list[ResourceCandidate] = Field(min_length=1, max_length=12)
    recommended_refs: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_refs(self) -> "RecommendResourcesInput":
        candidate_refs = [candidate.candidate_ref for candidate in self.candidates]
        if len(candidate_refs) != len(set(candidate_refs)):
            raise ValueError("candidate_ref values must be unique")
        if len(self.recommended_refs) != len(set(self.recommended_refs)):
            raise ValueError("recommended_refs must be unique")
        if not set(self.recommended_refs).issubset(candidate_refs):
            raise ValueError("recommended_refs must be a subset of candidates")
        return self


class ResourceInstallationOption(BaseModel):
    """One verified installation path for an installable resource."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    option_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    form_kind: Literal[
        "SKILL_CONFIG",
        "MCP_REMOTE",
        "MCP_CONTAINER",
    ]
    config: dict[str, Any] | list[dict[str, Any]]


class RecommendedResource(BaseModel):
    """Frozen card-facing resource detail boundary (implemented in PR2)."""

    model_config = ConfigDict(extra="forbid")
    candidate: ResourceCandidate
    recommendation: Literal["recommended", "optional"]
    is_bound: bool = False
    form_kind: Literal[
        "TOOL_CONFIG",
        "SKILL_CONFIG",
        "MCP_REMOTE",
        "MCP_CONTAINER",
    ]
    config: dict[str, Any] | list[dict[str, Any]]
    installation_options: list[ResourceInstallationOption] = Field(
        default_factory=list
    )
    default_option_id: str | None = None

    @model_validator(mode="after")
    def validate_installation_options(self) -> "RecommendedResource":
        option_ids = [option.option_id for option in self.installation_options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("installation option IDs must be unique")
        if self.installation_options:
            if self.default_option_id not in set(option_ids):
                raise ValueError("default_option_id must reference an option")
        elif self.default_option_id is not None:
            raise ValueError("default_option_id requires installation options")
        return self


class RecommendResourcesOutput(BaseModel):
    """Frozen successful recommend-resources output (implemented in PR2)."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["success"] = "success"
    resources: list[RecommendedResource]


class ResourceToolError(BaseModel):
    """Stable non-sensitive error shared by PR2 resource tools."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["error"] = "error"
    code: Literal[
        "invalid_requirements",
        "resource_search_failed",
        "invalid_candidates",
        "resource_not_found",
        "resource_not_visible",
        "resource_resolution_failed",
        "agent_context_mismatch",
        "agent_not_found",
        "agent_not_draft",
        "agent_deleted",
        "agent_read_only",
        "unauthorized",
    ]
    retryable: bool
    candidates: list[ResourceCandidate] = Field(default_factory=list)
    resources: list[RecommendedResource] = Field(default_factory=list)
    uncovered_requirement_ids: list[str] = Field(default_factory=list)


class InstalledResourceBindingPayload(BaseModel):
    """Verified NL2A payload for the installed-resource binding card."""

    model_config = ConfigDict(extra="forbid")
    subtype: Literal["installed_resource_binding"] = "installed_resource_binding"
    agent_id: int = Field(gt=0)
    resources: list[RecommendedResource] = Field(max_length=12)
    requirements: list[ResourceRequirement] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_installed_sources(self) -> "InstalledResourceBindingPayload":
        if any(
            resource.candidate.source not in INSTALLED_RESOURCE_SOURCES
            or resource.installation_options
            for resource in self.resources
        ):
            raise ValueError("binding resources must already be installed")
        return self


class SuggestedResourceInstallationPayload(BaseModel):
    """Verified NL2A payload for the per-resource installation card."""

    model_config = ConfigDict(extra="forbid")
    subtype: Literal["suggested_resource_installation"] = (
        "suggested_resource_installation"
    )
    agent_id: int = Field(gt=0)
    resources: list[RecommendedResource] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_installable_sources(
        self,
    ) -> "SuggestedResourceInstallationPayload":
        if any(
            resource.candidate.source not in UNINSTALLED_RESOURCE_SOURCES
            or not resource.installation_options
            for resource in self.resources
        ):
            raise ValueError("installation resources must be installable")
        return self


class AgentDraftFields(BaseModel):
    """Whitelisted partial fields accepted by the database draft tool."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    description: str | None = None
    duty_prompt: str | None = None
    constraint_prompt: str | None = None
    few_shots_prompt: str | None = None
    greeting_message: str | None = None
    example_questions: list[str] | None = Field(default=None, max_length=6)

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null(cls, value: Any) -> Any:
        if isinstance(value, dict):
            null_fields = [key for key, item in value.items() if item is None]
            if null_fields:
                raise ValueError("agent draft fields cannot be null")
        return value

    @model_validator(mode="after")
    def reject_empty_patch(self) -> "AgentDraftFields":
        if not self.model_fields_set:
            raise ValueError("agent draft fields cannot be empty")
        return self


class SaveAgentDraftFieldsInput(BaseModel):
    """Frozen input model for existing-draft persistence."""

    model_config = ConfigDict(extra="forbid")
    agent_id: int = Field(gt=0)
    fields: AgentDraftFields


class SaveAgentDraftFieldsSuccess(BaseModel):
    """Stable success result returned by save_agent_draft_fields."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["success"] = "success"
    agent_id: int = Field(gt=0)
    created: Literal[False] = False
    updated_fields: list[str]

    @model_validator(mode="after")
    def validate_updated_fields(self) -> "SaveAgentDraftFieldsSuccess":
        if (
            not self.updated_fields
            or len(self.updated_fields) != len(set(self.updated_fields))
            or any(
                field_name not in _NL2AGENT_DRAFT_SYNC_FIELDS
                for field_name in self.updated_fields
            )
        ):
            raise ValueError("updated_fields must be non-empty, unique draft fields")
        return self


class SaveAgentDraftFieldsError(BaseModel):
    """Stable non-sensitive error returned by save_agent_draft_fields."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["error"] = "error"
    agent_id: int | None = None
    created: Literal[False] = False
    updated_fields: list[str] = Field(default_factory=list)
    code: Literal[
        "invalid_agent_fields",
        "agent_not_found",
        "agent_not_draft",
        "agent_deleted",
        "agent_read_only",
        "agent_context_mismatch",
        "draft_save_failed",
        "draft_fields_incomplete",
        "prompt_fields_incomplete",
        "unauthorized",
    ]
    retryable: bool


class RequirementClarificationOption(BaseModel):
    """One selectable answer in a clarification question."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    option_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=300)


class RequirementClarificationQuestion(BaseModel):
    """One schema-driven clarification question rendered by the old frontend."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question_id: str = Field(min_length=1, max_length=100)
    question_type: Literal["single_choice", "multiple_choice", "text"]
    title: str = Field(min_length=1, max_length=500)
    required: bool = True
    options: list[RequirementClarificationOption] = Field(default_factory=list)
    allow_other: bool = True
    other_input_expanded: bool = True

    @model_validator(mode="before")
    @classmethod
    def apply_question_type_defaults(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("question_type") == "text":
            normalized = dict(value)
            normalized.setdefault("allow_other", False)
            normalized.setdefault("other_input_expanded", False)
            return normalized
        return value

    @model_validator(mode="after")
    def validate_options(self) -> "RequirementClarificationQuestion":
        if self.question_type == "text":
            if self.options:
                raise ValueError("text clarification questions cannot have options")
            if self.allow_other or self.other_input_expanded:
                raise ValueError(
                    "text clarification questions cannot allow other answers"
                )
        elif not self.options:
            raise ValueError("choice clarification questions require options")
        elif not self.allow_other or not self.other_input_expanded:
            raise ValueError(
                "choice clarification questions require expanded other input"
            )
        return self


class RequirementClarificationPayload(BaseModel):
    """NL2A payload for the PR1 clarification card."""

    model_config = ConfigDict(extra="forbid")
    subtype: Literal["requirement_clarification"] = "requirement_clarification"
    agent_id: int = Field(gt=0)
    questions: list[RequirementClarificationQuestion] = Field(
        min_length=1,
        max_length=MAX_REQUIREMENT_CLARIFICATION_QUESTIONS,
    )


class ResourceGapResolutionPayload(BaseModel):
    """NL2Agent payload for resolving requirements without matching resources."""

    model_config = ConfigDict(extra="forbid")

    subtype: Literal["resource_gap_resolution"] = "resource_gap_resolution"
    agent_id: int = Field(gt=0)
    requirements: list[ResourceRequirement] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_requirement_ids(self) -> "ResourceGapResolutionPayload":
        requirement_ids = [item.requirement_id for item in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirement_id values must be unique")
        return self


class InstalledMcpToolRecommendation(BaseModel):
    """Safe display metadata for one installed MCP tool recommendation."""

    tool_id: int
    name: str
    origin_name: str | None = None
    description: str
    source: Literal["mcp"] = "mcp"
    usage: str
    labels: list[str]
    inputs: dict[str, Any]
    score: float


class SearchInstalledMcpToolsObservation(BaseModel):
    """Successful structured observation returned to the agent."""

    subtype: Literal["local_mcp_recommendation"] = "local_mcp_recommendation"
    status: Literal["success"] = "success"
    recommendation_count: int
    recommendations: list[InstalledMcpToolRecommendation]


class SearchInstalledMcpToolsErrorObservation(BaseModel):
    """Safe structured error returned to the agent."""

    subtype: Literal["local_mcp_recommendation"] = "local_mcp_recommendation"
    status: Literal["error"] = "error"
    code: Literal["invalid_keywords", "tool_search_failed"]
    retryable: Literal[True] = True


_NEXT_ACTION_SUBTYPE = {
    "INSTALL": "suggested_resource_installation",
    "RESOLVE_GAP": "resource_gap_resolution",
    "BIND": "installed_resource_binding",
}


def _build_v2_resource_payload(
    *,
    subtype: NL2A_SUBTYPES,
    agent_id: int,
    resolution: ResourceResolutionOutput,
) -> BaseModel:
    """Build the card selected by a verified unified resolution result."""

    expected_subtype = _NEXT_ACTION_SUBTYPE[resolution.next_action]
    if subtype != expected_subtype:
        raise ValueError(
            f"{subtype} does not match next_action {resolution.next_action}"
        )

    resources_by_ref = {
        resource.candidate_ref: resource for resource in resolution.resources
    }
    if subtype == "suggested_resource_installation":
        selected_refs = {
            match.candidate_ref
            for item in resolution.requirements
            if item.state == "installable"
            for match in item.installable_matches
        }
        return SuggestedResourceInstallationPayloadV2(
            agent_id=agent_id,
            resources=[
                resource
                for ref, resource in resources_by_ref.items()
                if ref in selected_refs
            ],
        )
    if subtype == "resource_gap_resolution":
        gap_requirements: list[ResourceGapRequirement] = []
        for item in resolution.requirements:
            if item.state != "uncovered":
                continue
            weak_references = []
            for match in item.weak_references:
                resource = resources_by_ref.get(match.candidate_ref)
                if resource is None:
                    continue
                weak_references.append(WeakResourceReference(
                    candidate_ref=resource.candidate_ref,
                    name=resource.name,
                    description=resource.description,
                    source=resource.source,
                    score=match.score,
                ))
            gap_requirements.append(ResourceGapRequirement(
                requirement_id=item.requirement.requirement_id,
                query=item.requirement.query,
                search_terms=item.requirement.search_terms,
                weak_references=weak_references,
            ))
        return ResourceGapResolutionPayloadV2(
            agent_id=agent_id,
            requirements=gap_requirements,
        )

    selected_refs = {
        match.candidate_ref
        for item in resolution.requirements
        if item.state == "covered"
        for match in item.installed_matches
    }
    return InstalledResourceBindingPayloadV2(
        agent_id=agent_id,
        resources=[
            resource
            for ref, resource in resources_by_ref.items()
            if ref in selected_refs
        ],
        requirements=[item.requirement for item in resolution.requirements],
    )


def build_nl2a_wrapper(
    subtype: NL2A_SUBTYPES,
    agent_id: int,
    resource_result: (
        dict[str, Any]
        | RecommendResourcesOutput
        | ResourceResolutionOutput
        | None
    ) = None,
    questions: list[RequirementClarificationQuestion] | None = None,
    requirements: list[ResourceRequirement] | None = None,
) -> str:
    """Fill the JSON template selected by subtype and return its wrapper."""

    if subtype == "requirement_clarification":
        if questions is None:
            raise ValueError("requirement_clarification requires questions")
        output = RequirementClarificationPayload(
            agent_id=agent_id,
            questions=questions,
        ).model_dump(mode="json")
    elif resource_result is not None and (
        isinstance(resource_result, ResourceResolutionOutput)
        or (
            isinstance(resource_result, dict)
            and "next_action" in resource_result
        )
    ):
        resolution = ResourceResolutionOutput.model_validate(resource_result)
        output = _build_v2_resource_payload(
            subtype=subtype,
            agent_id=agent_id,
            resolution=resolution,
        ).model_dump(mode="json")
    elif subtype == "resource_gap_resolution":
        if requirements is None:
            raise ValueError("resource_gap_resolution requires requirements")
        output = ResourceGapResolutionPayload(
            agent_id=agent_id,
            requirements=requirements,
        ).model_dump(mode="json")
    elif subtype in {
        "suggested_resource_installation",
        "installed_resource_binding",
    }:
        if agent_id is None or resource_result is None:
            raise ValueError(
                f"{subtype} requires agent_id and resource_result"
            )
        verified = RecommendResourcesOutput.model_validate(resource_result)
        payload_model = (
            SuggestedResourceInstallationPayload
            if subtype == "suggested_resource_installation"
            else InstalledResourceBindingPayload
        )
        payload_kwargs = {"agent_id": agent_id, "resources": verified.resources}
        if subtype == "installed_resource_binding":
            payload_kwargs["requirements"] = requirements or []
        output = payload_model(**payload_kwargs).model_dump(mode="json")
    else:
        raise ValueError(f"unsupported nl2a subtype: {subtype}")

    return _serialize_nl2a_payload(output)


def _serialize_nl2a_payload(output: BaseModel | dict[str, Any]) -> str:
    payload = (
        output.model_dump(mode="json")
        if isinstance(output, BaseModel)
        else output
    )
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"<nl2a>\n{serialized}\n</nl2a>\nNL2A payload generated."


def create_nl2agent_mcp_tool_configs() -> list[ToolConfig]:
    """Create fresh SDK configs for the NL2Agent business tools."""
    return [
        ToolConfig(
            class_name=RESOLVE_RESOURCE_REQUIREMENTS_NAME,
            name=RESOLVE_RESOURCE_REQUIREMENTS_NAME,
            description=RESOLVE_RESOURCE_REQUIREMENTS_DESCRIPTION,
            inputs=(
                '{"agent_id":"int",'
                '"requirements":"list[ResourceRequirement]",'
                '"phase":"INITIAL | POST_INSTALL | POST_GAP",'
                '"exclude_refs":"list[str]"}'
            ),
            output_type="object",
            params={},
            source="mcp",
            usage="outer-apis",
        ),
        ToolConfig(
            class_name=SAVE_AGENT_DRAFT_FIELDS_NAME,
            name=SAVE_AGENT_DRAFT_FIELDS_NAME,
            description=SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION,
            inputs=json.dumps(
                {
                    "agent_id": "int",
                    "fields": {
                        field_name: field_type
                        for field_name, field_type in {
                            "description": "str",
                            "duty_prompt": "str",
                            "constraint_prompt": "str",
                            "few_shots_prompt": "str",
                            "greeting_message": "str",
                            "example_questions": "list[str]",
                        }.items()
                    },
                },
                separators=(",", ":"),
            ),
            output_type="string",
            params={},
            source="mcp",
            usage="outer-apis",
        ),
        ToolConfig(
            class_name=NL2A_WRAPPER_NAME,
            name=NL2A_WRAPPER_NAME,
            description=NL2A_WRAPPER_DESCRIPTION,
            inputs=json.dumps(
                {
                    "subtype": "str",
                    "agent_id": "int",
                    "resource_result": "ResourceResolutionOutput | None",
                    "questions": "list[RequirementClarificationQuestion] | None",
                },
                separators=(",", ":"),
            ),
            output_type="string",
            params={},
            source="mcp",
            usage="outer-apis",
        ),
    ]


class AgentContextMismatchError(Exception):
    """The model supplied an Agent ID that conflicts with trusted run context."""


def _resolve_agent_context_id(agent_id: int | None) -> int:
    """Resolve and validate the request-scoped Agent ID forwarded by NL2Agent."""

    try:
        raw_context_id = get_http_request().headers.get(NL2AGENT_AGENT_ID_HEADER)
    except RuntimeError:
        # Pure unit calls have no FastMCP HTTP context.
        raw_context_id = None
    if raw_context_id is None:
        if (
            not isinstance(agent_id, int)
            or isinstance(agent_id, bool)
            or agent_id <= 0
        ):
            raise AgentContextMismatchError("agent_context_mismatch")
        return agent_id
    try:
        context_id = int(raw_context_id)
    except (TypeError, ValueError) as exc:
        raise AgentContextMismatchError("agent_context_mismatch") from exc
    if (
        context_id <= 0
        or not isinstance(agent_id, int)
        or isinstance(agent_id, bool)
        or agent_id != context_id
    ):
        raise AgentContextMismatchError("agent_context_mismatch")
    return context_id


def _agent_context_error(code: str = "agent_context_mismatch") -> str:
    return json.dumps(
        {"status": "error", "code": code, "retryable": False},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _dump_tool_search_observation(
    observation: SearchInstalledMcpToolsObservation
    | SearchInstalledMcpToolsErrorObservation,
) -> dict[str, Any]:
    """Dump one tool search observation for direct wrapper consumption."""
    return observation.model_dump(mode="json")


def _prepare_search_keywords(keywords: list[str]) -> list[str] | None:
    """Validate and de-duplicate keyword input while preserving its order."""

    if not 1 <= len(keywords) <= 10:
        return None

    prepared_keywords: list[str] = []
    seen: set[str] = set()
    for raw_keyword in keywords:
        stripped_keyword = raw_keyword.strip()
        if not stripped_keyword or len(stripped_keyword) > 100:
            return None

        normalized_keyword = unicodedata.normalize(
            "NFKC", stripped_keyword
        ).casefold()
        normalized_keyword = re.sub(r"\s+", " ", normalized_keyword)
        if normalized_keyword in seen:
            continue

        seen.add(normalized_keyword)
        prepared_keywords.append(stripped_keyword)

    return prepared_keywords


async def search_installed_mcp_tools(keywords: list[str]) -> dict[str, Any]:
    """Search safe MCP tool metadata for the tenant in the current request."""

    prepared_keywords = _prepare_search_keywords(keywords)
    if prepared_keywords is None:
        return _dump_tool_search_observation(
            SearchInstalledMcpToolsErrorObservation(code="invalid_keywords")
        )

    try:
        # Keep NL2Agent runtime dependencies out of the MCP server startup path.
        from services.nl2agent_service import search_installed_mcp_tools_by_query

        authorization = get_http_request().headers.get("Authorization")
        _, tenant_id = get_current_user_id(authorization)
        recommendations = search_installed_mcp_tools_by_query(
            tenant_id=tenant_id,
            query_text=" ".join(prepared_keywords),
        )
    except Exception:
        logger.exception("Failed to search installed MCP tools from local MCP service")
        return _dump_tool_search_observation(
            SearchInstalledMcpToolsErrorObservation(code="tool_search_failed")
        )

    return _dump_tool_search_observation(
        SearchInstalledMcpToolsObservation(
            recommendation_count=len(recommendations),
            recommendations=recommendations,
        )
    )


def _dump_resource_tool_error(
    code: str,
    *,
    retryable: bool,
) -> dict[str, Any]:
    return ResourceToolError(
        code=code,
        retryable=retryable,
    ).model_dump(mode="json")


async def search_installed_resources(
    agent_id: int,
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Search installed resources through a safe tenant-scoped service boundary."""

    try:
        payload = SearchInstalledResourcesInput(requirements=requirements)
    except ValidationError:
        return _dump_resource_tool_error(
            "invalid_requirements",
            retryable=False,
        )

    try:
        resolved_agent_id = _resolve_agent_context_id(agent_id)
    except AgentContextMismatchError:
        return _dump_resource_tool_error(
            "agent_context_mismatch",
            retryable=False,
        )

    try:
        from services.agent_draft_permission_service import (
            AgentDraftEditError,
            require_agent_draft_edit,
        )
        from services.nl2agent_service import search_installed_resources_impl

        authorization = get_http_request().headers.get("Authorization")
        user_id, tenant_id = get_current_user_id(authorization)
        require_agent_draft_edit(
            agent_id=resolved_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        result = await search_installed_resources_impl(
            requirements=payload.requirements,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return result.model_dump(mode="json")
    except AgentDraftEditError as exc:
        return _dump_resource_tool_error(exc.code, retryable=False)
    except (PermissionError, UnauthorizedError):
        return _dump_resource_tool_error("unauthorized", retryable=False)
    except Exception:
        logger.exception("Failed to search installed NL2Agent resources")
        return _dump_resource_tool_error(
            "resource_search_failed",
            retryable=True,
        )


async def search_uninstalled_resources(
    agent_id: int,
    requirements: list[dict[str, Any]],
    exclude_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Search installable resources through a tenant-scoped service boundary."""

    try:
        payload = SearchUninstalledResourcesInput(
            requirements=requirements,
            exclude_refs=exclude_refs or [],
        )
    except ValidationError:
        return _dump_resource_tool_error("invalid_requirements", retryable=False)

    try:
        resolved_agent_id = _resolve_agent_context_id(agent_id)
    except AgentContextMismatchError:
        return _dump_resource_tool_error(
            "agent_context_mismatch", retryable=False
        )

    try:
        from services.agent_draft_permission_service import (
            AgentDraftEditError,
            require_agent_draft_edit,
        )
        from services.nl2agent_service import search_uninstalled_resources_impl

        authorization = get_http_request().headers.get("Authorization")
        user_id, tenant_id = get_current_user_id(authorization)
        require_agent_draft_edit(
            agent_id=resolved_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        result = await search_uninstalled_resources_impl(
            requirements=payload.requirements,
            exclude_refs=payload.exclude_refs,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return result.model_dump(mode="json")
    except AgentDraftEditError as exc:
        return _dump_resource_tool_error(exc.code, retryable=False)
    except (PermissionError, UnauthorizedError):
        return _dump_resource_tool_error("unauthorized", retryable=False)
    except Exception:
        logger.exception("Failed to search uninstalled NL2Agent resources")
        return _dump_resource_tool_error(
            "resource_search_failed", retryable=True
        )


async def resolve_resource_requirements(
    agent_id: int,
    requirements: list[dict[str, Any]],
    phase: ResourceResolutionPhase,
    exclude_refs: list[str] | None = None,
    verification_required: bool = False,
    capability_verifications: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one complete, backend-owned resource resolution decision."""

    try:
        payload = ResolveResourceRequirementsInput(
            requirements=requirements,
            phase=phase,
            exclude_refs=exclude_refs or [],
            verification_required=verification_required,
            capability_verifications=capability_verifications,
        )
    except ValidationError:
        return _dump_resource_tool_error("invalid_requirements", retryable=False)

    try:
        resolved_agent_id = _resolve_agent_context_id(agent_id)
    except AgentContextMismatchError:
        return _dump_resource_tool_error(
            "agent_context_mismatch", retryable=False
        )

    try:
        from services.agent_draft_permission_service import (
            AgentDraftEditError,
            require_agent_draft_edit,
        )
        from services.nl2agent_service import resolve_resource_requirements_impl

        authorization = get_http_request().headers.get("Authorization")
        user_id, tenant_id = get_current_user_id(authorization)
        require_agent_draft_edit(
            agent_id=resolved_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            verification_required=payload.verification_required,
            capability_verifications=payload.capability_verifications,
        )
        result = await resolve_resource_requirements_impl(
            requirements=payload.requirements,
            phase=payload.phase,
            exclude_refs=payload.exclude_refs,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return result.model_dump(mode="json")
    except AgentDraftEditError as exc:
        return _dump_resource_tool_error(exc.code, retryable=False)
    except (PermissionError, UnauthorizedError):
        return _dump_resource_tool_error("unauthorized", retryable=False)
    except Exception:
        logger.exception("Failed to resolve NL2Agent resource requirements")
        return _dump_resource_tool_error(
            "resource_resolution_failed", retryable=True
        )


async def recommend_resources(
    agent_id: int,
    candidates: list[dict[str, Any]],
    recommended_refs: list[str],
) -> dict[str, Any]:
    """Resolve candidates into verified installation or binding metadata."""

    try:
        payload = RecommendResourcesInput(
            candidates=candidates,
            recommended_refs=recommended_refs,
        )
    except ValidationError:
        return _dump_resource_tool_error("invalid_candidates", retryable=False)

    try:
        resolved_agent_id = _resolve_agent_context_id(agent_id)
    except AgentContextMismatchError:
        return _dump_resource_tool_error(
            "agent_context_mismatch",
            retryable=False,
        )

    try:
        from services.agent_draft_permission_service import (
            AgentDraftEditError,
            require_agent_draft_edit,
        )
        from services.nl2agent_service import (
            Nl2AgentResourceError,
            recommend_resources_impl,
        )

        authorization = get_http_request().headers.get("Authorization")
        user_id, tenant_id = get_current_user_id(authorization)
        require_agent_draft_edit(
            agent_id=resolved_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        result = await recommend_resources_impl(
            agent_id=resolved_agent_id,
            candidates=payload.candidates,
            recommended_refs=payload.recommended_refs,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return result.model_dump(mode="json")
    except AgentDraftEditError as exc:
        return _dump_resource_tool_error(exc.code, retryable=False)
    except Nl2AgentResourceError as exc:
        return _dump_resource_tool_error(
            exc.code,
            retryable=exc.retryable,
        )
    except (PermissionError, UnauthorizedError):
        return _dump_resource_tool_error("unauthorized", retryable=False)
    except Exception:
        logger.exception("Failed to resolve NL2Agent resources")
        return _dump_resource_tool_error(
            "resource_resolution_failed",
            retryable=True,
        )


async def nl2a_wrapper(
    subtype: Literal[
        "requirement_clarification",
        "suggested_resource_installation",
        "installed_resource_binding",
        "resource_gap_resolution",
    ],
    agent_id: int,
    resource_result: dict[str, Any] | None = None,
    questions: list[RequirementClarificationQuestion] | None = None,
    requirements: list[ResourceRequirement] | None = None,
) -> str:
    """Return the NL2Agent JSON template selected by subtype in its wrapper."""

    from services.agent_draft_permission_service import (
        AgentDraftEditError,
        require_agent_draft_edit,
    )

    try:
        resolved_agent_id = _resolve_agent_context_id(agent_id)
        authorization = get_http_request().headers.get("Authorization")
        user_id, tenant_id = get_current_user_id(authorization)
        require_agent_draft_edit(
            agent_id=resolved_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except AgentContextMismatchError:
        return _agent_context_error()
    except AgentDraftEditError as exc:
        return _agent_context_error(exc.code)
    except (PermissionError, UnauthorizedError):
        return _agent_context_error("unauthorized")

    if resource_result is not None and "next_action" in resource_result:
        supplied = ResourceResolutionOutput.model_validate(resource_result)
        if not supplied.requirements:
            if supplied.resources or supplied.next_action != "BIND":
                raise ValueError("empty resource resolution must bind no resources")
            verified = supplied
        else:
            from services.nl2agent_service import resolve_resource_requirements_impl

            verified = await resolve_resource_requirements_impl(
                requirements=[item.requirement for item in supplied.requirements],
                phase=supplied.phase,
                exclude_refs=[],
                tenant_id=tenant_id,
                user_id=user_id,
            )
        return build_nl2a_wrapper(
            subtype=subtype,
            agent_id=resolved_agent_id,
            resource_result=verified,
        )

    if subtype in {
        "suggested_resource_installation",
        "installed_resource_binding",
    }:
        if resource_result is None:
            raise ValueError(f"{subtype} requires agent_id and resource_result")
        supplied = RecommendResourcesOutput.model_validate(resource_result)
        from services.nl2agent_service import recommend_resources_impl

        sources = {resource.candidate.source for resource in supplied.resources}
        required_sources = (
            UNINSTALLED_RESOURCE_SOURCES
            if subtype == "suggested_resource_installation"
            else INSTALLED_RESOURCE_SOURCES
        )
        if not sources or not sources.issubset(required_sources):
            raise ValueError(f"invalid resources for {subtype}")
        verified = await recommend_resources_impl(
            agent_id=resolved_agent_id,
            candidates=[resource.candidate for resource in supplied.resources],
            recommended_refs=[
                resource.candidate.candidate_ref
                for resource in supplied.resources
                if resource.recommendation == "recommended"
            ],
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return build_nl2a_wrapper(
            subtype=subtype,
            agent_id=resolved_agent_id,
            resource_result=verified,
            requirements=requirements,
        )

    return build_nl2a_wrapper(
        subtype=subtype,
        agent_id=resolved_agent_id,
        resource_result=resource_result,
        questions=questions,
        requirements=requirements,
    )


def _serialize_agent_draft_save_result(
    result: SaveAgentDraftFieldsSuccess | SaveAgentDraftFieldsError,
    attempted_fields: list[str] | None = None,
    failed_fields: list[str] | None = None,
    generation_completed: bool = False,
) -> str:
    payload = result.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if isinstance(result, SaveAgentDraftFieldsSuccess):
        state_payload = (
            {
                "event": "agent_generation_completed",
                "agent_id": result.agent_id,
            }
            if generation_completed
            else {
                "event": "agent_draft_fields_saved",
                "agent_id": result.agent_id,
                "updated_fields": result.updated_fields,
            }
        )
        state = json.dumps(
            state_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return f"{serialized}\n<nl2a_state>{state}</nl2a_state>"

    prompt_fields = sorted(
        set(failed_fields or attempted_fields or []) & _NL2AGENT_PROMPT_FIELDS
    )
    if (
        isinstance(result, SaveAgentDraftFieldsError)
        and isinstance(result.agent_id, int)
        and result.agent_id > 0
        and prompt_fields
    ):
        state = json.dumps(
            {
                "event": "prompt_generation_failed",
                "agent_id": result.agent_id,
                "failed_fields": prompt_fields,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return f"{serialized}\n<nl2a_state>{state}</nl2a_state>"
    return serialized


async def save_agent_draft_fields(
    agent_id: int,
    fields: dict[str, Any],
) -> str:
    """Validate and persist a tenant-scoped ordinary AgentInfo draft patch."""
    try:
        payload = SaveAgentDraftFieldsInput(agent_id=agent_id, fields=fields)
    except ValidationError:
        try:
            error_agent_id = _resolve_agent_context_id(agent_id)
        except AgentContextMismatchError:
            error_agent_id = agent_id
        return _serialize_agent_draft_save_result(
            SaveAgentDraftFieldsError(
                agent_id=error_agent_id,
                code="invalid_agent_fields",
                retryable=False,
            ),
            list(fields) if isinstance(fields, dict) else [],
        )

    try:
        resolved_agent_id = _resolve_agent_context_id(payload.agent_id)
    except AgentContextMismatchError:
        return _serialize_agent_draft_save_result(
            SaveAgentDraftFieldsError(
                agent_id=payload.agent_id,
                code="agent_context_mismatch",
                retryable=False,
            )
        )

    try:
        from services.nl2agent_service import (
            Nl2AgentCompletionError,
            Nl2AgentDraftSaveError,
            save_agent_draft_fields_impl,
            validate_agent_generation_complete_impl,
        )

        authorization = get_http_request().headers.get("Authorization")
        user_id, tenant_id = get_current_user_id(authorization)
        result = save_agent_draft_fields_impl(
            agent_id=resolved_agent_id,
            fields=payload.fields,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        success = SaveAgentDraftFieldsSuccess.model_validate(result)
        updated_fields = set(success.updated_fields)
        if updated_fields & _NL2AGENT_PROMPT_FIELDS:
            try:
                await validate_agent_generation_complete_impl(
                    agent_id=resolved_agent_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            except Nl2AgentCompletionError as exc:
                if not _NL2AGENT_FINAL_PROMPT_BATCH.issubset(updated_fields):
                    return _serialize_agent_draft_save_result(success)
                return _serialize_agent_draft_save_result(
                    SaveAgentDraftFieldsError(
                        agent_id=resolved_agent_id,
                        code=exc.code,
                        retryable=exc.code == "prompt_fields_incomplete",
                    ),
                    failed_fields=exc.failed_fields,
                )
            return _serialize_agent_draft_save_result(
                success,
                generation_completed=True,
            )
        return _serialize_agent_draft_save_result(success)
    except Nl2AgentDraftSaveError as exc:
        return _serialize_agent_draft_save_result(
            SaveAgentDraftFieldsError(
                agent_id=resolved_agent_id,
                code=exc.code,
                retryable=exc.retryable,
            ),
            list(payload.fields.model_fields_set),
        )
    except (PermissionError, UnauthorizedError):
        return _serialize_agent_draft_save_result(
            SaveAgentDraftFieldsError(
                agent_id=resolved_agent_id,
                code="unauthorized",
                retryable=False,
            ),
            list(payload.fields.model_fields_set),
        )
    except Exception:
        logger.exception("Failed to save NL2Agent draft fields")
        return _serialize_agent_draft_save_result(
            SaveAgentDraftFieldsError(
                agent_id=resolved_agent_id,
                code="draft_save_failed",
                retryable=True,
            ),
            list(payload.fields.model_fields_set),
        )
