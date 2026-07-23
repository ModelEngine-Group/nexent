"""Typed NL2AGENT workflow state and deterministic stage evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from utils.nl2agent_catalog_snapshot import (
    CATALOG_HASH_PATTERN,
    CATALOG_VERSION_PATTERN,
)


WORKFLOW_SCHEMA_VERSION = 3
MAX_WORKFLOW_COLLECTION_ITEMS = 100

PositiveStrictInt = Annotated[int, Field(strict=True, ge=1)]
BoundedItemKey = Annotated[str, Field(min_length=1, max_length=300)]

CardType = Literal[
    "requirements_summary",
    "model_selection",
    "local_resources",
    "web_mcp",
    "web_skill",
    "agent_identity",
    "final_review",
]

WorkflowStage = Literal[
    "revision_routing",
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


class RequirementsReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["collecting", "awaiting_confirmation", "confirmed"] = "collecting"
    summary: Optional[Dict[str, str]] = None
    fingerprint: str = ""


class RecommendationBatch(BaseModel):
    """One immutable search proof and its presentation/application lifecycle."""

    model_config = ConfigDict(extra="forbid")

    resource_type: Literal["local", "mcp", "skill"]
    status: Literal["searched", "presented", "applying", "applied", "skipped", "completed"]
    catalog_version: str = Field(default="", max_length=64)
    catalog_hash: str = Field(default="", max_length=64)
    tool_ids: List[PositiveStrictInt] = Field(default_factory=list, max_length=100)
    skill_ids: List[PositiveStrictInt] = Field(default_factory=list, max_length=100)
    item_keys: List[BoundedItemKey] = Field(default_factory=list, max_length=100)
    applied_tool_ids: List[PositiveStrictInt] = Field(
        default_factory=list, max_length=100
    )
    applied_skill_ids: List[PositiveStrictInt] = Field(
        default_factory=list, max_length=100
    )
    operation_id: Optional[str] = Field(default=None, max_length=128)

    @field_validator("catalog_version")
    @classmethod
    def validate_catalog_version(cls, value: str) -> str:
        if value and not CATALOG_VERSION_PATTERN.fullmatch(value):
            raise ValueError("catalog_version is malformed")
        return value

    @field_validator("catalog_hash")
    @classmethod
    def validate_catalog_hash(cls, value: str) -> str:
        if value and not CATALOG_HASH_PATTERN.fullmatch(value):
            raise ValueError("catalog_hash is malformed")
        return value

    @model_validator(mode="after")
    def validate_catalog_identity_pair(self) -> "RecommendationBatch":
        if bool(self.catalog_version) != bool(self.catalog_hash):
            raise ValueError("catalog_version and catalog_hash must be provided together")
        return self


class McpWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = Field(min_length=1, max_length=300)
    option_id: Optional[str] = Field(default=None, max_length=100)
    installation_key: Optional[str] = Field(default=None, max_length=300)
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
    mcp_id: Optional[PositiveStrictInt] = None
    discovered_tool_ids: List[PositiveStrictInt] = Field(
        default_factory=list, max_length=100
    )
    bound_tool_ids: List[PositiveStrictInt] = Field(
        default_factory=list, max_length=100
    )
    error: Optional[str] = Field(default=None, max_length=1000)


class Nl2AgentWorkflowState(BaseModel):
    """PostgreSQL-persisted workflow state. Old schemas are intentionally rejected."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3] = WORKFLOW_SCHEMA_VERSION
    revision: int = Field(default=0, ge=0)
    revision_mode: bool = False
    conversation_id: PositiveStrictInt
    requirements_review: RequirementsReview = Field(default_factory=RequirementsReview)
    model_selection_confirmed: bool = False
    recommendations: Dict[str, RecommendationBatch] = Field(
        default_factory=dict, max_length=MAX_WORKFLOW_COLLECTION_ITEMS
    )
    identity_confirmed: bool = False
    mcp_workflows: Dict[str, McpWorkflow] = Field(
        default_factory=dict, max_length=MAX_WORKFLOW_COLLECTION_ITEMS
    )
    online_configuration_confirmed: bool = False

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("conversation_id must be positive")
        return value


class WorkflowSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_stage: WorkflowStage
    expected_card_types: List[CardType]
    allowed_card_types: List[CardType]
    allowed_actions: List[str]
    requirements_status: str
    model_selection_confirmed: bool
    local_review_status: Literal["missing", "pending", "complete"]
    mcp_batch_registered: bool
    skill_batch_registered: bool
    online_configuration_confirmed: bool
    unresolved_mcp_count: int
    identity_confirmed: bool


@dataclass(frozen=True)
class _WorkflowFacts:
    local_status: Literal["missing", "pending", "complete"]
    local_card_pending: bool
    mcp_registered: bool
    skill_registered: bool
    mcp_card_pending: bool
    skill_card_pending: bool
    unresolved_mcp_count: int

    @property
    def all_online_registered(self) -> bool:
        return self.mcp_registered and self.skill_registered


@dataclass(frozen=True)
class _StageDecision:
    stage: WorkflowStage
    expected: List[CardType]
    allowed_cards: List[CardType]
    allowed: List[str]


def _workflow_facts(state: Nl2AgentWorkflowState) -> _WorkflowFacts:
    local_batches = [batch for batch in state.recommendations.values() if batch.resource_type == "local"]
    if not local_batches:
        local_status: Literal["missing", "pending", "complete"] = "missing"
    elif any(
        batch.status in {"searched", "presented", "applying"} for batch in local_batches
    ):
        local_status = "pending"
    else:
        local_status = "complete"

    online_types = {
        batch.resource_type
        for batch in state.recommendations.values()
        if batch.resource_type in {"mcp", "skill"}
    }
    return _WorkflowFacts(
        local_status=local_status,
        local_card_pending=any(
            batch.resource_type == "local" and batch.status == "searched"
            for batch in state.recommendations.values()
        ),
        mcp_registered="mcp" in online_types,
        skill_registered="skill" in online_types,
        mcp_card_pending=any(
            batch.resource_type == "mcp" and batch.status == "searched"
            for batch in state.recommendations.values()
        ),
        skill_card_pending=any(
            batch.resource_type == "skill" and batch.status == "searched"
            for batch in state.recommendations.values()
        ),
        unresolved_mcp_count=sum(
            workflow.status in {"installing", "connected"}
            for workflow in state.mcp_workflows.values()
        ),
    )


def _select_stage(
    state: Nl2AgentWorkflowState,
    facts: _WorkflowFacts,
) -> _StageDecision:
    if state.revision_mode:
        return _StageDecision(
            "revision_routing",
            [],
            [
                "requirements_summary",
                "model_selection",
                "local_resources",
                "web_mcp",
                "web_skill",
                "agent_identity",
                "final_review",
            ],
            [
                "render_requirements_summary",
                "confirm_requirements",
                "revise_requirements",
                "select_models",
                "search_local_resources",
                "apply_local_resources",
                "skip_local_resources",
                "search_online_resources",
                "configure_online_resources",
                "complete_online_configuration",
                "save_identity",
            ],
        )
    requirements_status = state.requirements_review.status
    if requirements_status == "collecting":
        return _StageDecision(
            "requirements_collecting",
            [],
            [],
            ["clarify_requirements", "render_requirements_summary"],
        )
    if requirements_status == "awaiting_confirmation":
        return _StageDecision(
            "requirements_confirmation",
            [],
            [],
            ["confirm_requirements", "revise_requirements"],
        )
    if not state.model_selection_confirmed:
        return _StageDecision(
            "model_selection",
            ["model_selection"],
            ["model_selection"],
            ["select_models"],
        )
    if facts.local_status == "missing":
        return _StageDecision(
            "local_resource_search",
            ["local_resources"],
            ["local_resources"],
            ["search_local_resources"],
        )
    if facts.local_status == "pending":
        expected = ["local_resources"] if facts.local_card_pending else []
        return _StageDecision(
            "local_resource_review",
            expected,
            expected,
            ["apply_local_resources", "skip_local_resources"],
        )
    if not facts.all_online_registered:
        expected = [
            card_type
            for registered, card_type in (
                (facts.mcp_registered, "web_mcp"),
                (facts.skill_registered, "web_skill"),
            )
            if not registered
        ]
        allowed = ["search_online_resources"] + (
            ["configure_online_resources"]
            if facts.mcp_registered or facts.skill_registered
            else []
        )
        return _StageDecision("online_resource_search", expected, expected, allowed)
    if not state.online_configuration_confirmed:
        expected = [
            card_type
            for pending, card_type in (
                (facts.mcp_card_pending, "web_mcp"),
                (facts.skill_card_pending, "web_skill"),
            )
            if pending
        ]
        return _StageDecision(
            "online_resource_review",
            expected,
            expected,
            ["configure_online_resources", "complete_online_configuration"],
        )
    if not state.identity_confirmed:
        return _StageDecision(
            "agent_identity",
            ["agent_identity"],
            ["agent_identity"],
            ["save_identity"],
        )
    return _StageDecision(
        "final_review",
        ["final_review"],
        ["final_review"],
        ["publish_agent"],
    )


def evaluate_workflow(state: Nl2AgentWorkflowState) -> WorkflowSummary:
    """Return the single authoritative next stage for a persisted state."""
    facts = _workflow_facts(state)
    decision = _select_stage(state, facts)

    return WorkflowSummary(
        current_stage=decision.stage,
        expected_card_types=decision.expected,
        allowed_card_types=decision.allowed_cards,
        allowed_actions=decision.allowed,
        requirements_status=state.requirements_review.status,
        model_selection_confirmed=state.model_selection_confirmed,
        local_review_status=facts.local_status,
        mcp_batch_registered=facts.mcp_registered,
        skill_batch_registered=facts.skill_registered,
        online_configuration_confirmed=state.online_configuration_confirmed,
        unresolved_mcp_count=facts.unresolved_mcp_count,
        identity_confirmed=state.identity_confirmed,
    )


def state_to_dict(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
    return state.model_dump(mode="json")
