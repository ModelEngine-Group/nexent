"""Typed NL2AGENT workflow state and deterministic stage evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


WORKFLOW_SCHEMA_VERSION = 2

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
    model_config = ConfigDict(extra="allow")

    status: Literal["recommendations_ready", "applying", "applied", "skipped"]
    tool_ids: List[int] = Field(default_factory=list)
    skill_ids: List[int] = Field(default_factory=list)
    applied_tool_ids: List[int] = Field(default_factory=list)
    applied_skill_ids: List[int] = Field(default_factory=list)
    operation_id: Optional[str] = None


class OnlineRecommendationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: Literal["mcp", "skill"]
    item_keys: List[str] = Field(default_factory=list)
    status: Literal["recommendations_ready", "completed"]


class OnlineInstallation(BaseModel):
    """Internal reservation for one online resource installation."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["installing", "completed"]
    operation_id: str
    result: Dict[str, Any] = Field(default_factory=dict)


class TrustedSearchBatch(BaseModel):
    """Backend-recorded proof that an SDK search produced one result batch."""

    model_config = ConfigDict(extra="forbid")

    resource_type: Literal["local", "mcp", "skill"]
    tool_ids: List[int] = Field(default_factory=list)
    skill_ids: List[int] = Field(default_factory=list)
    item_keys: List[str] = Field(default_factory=list)


class McpWorkflow(BaseModel):
    model_config = ConfigDict(extra="allow")

    recommendation_id: str
    option_id: Optional[str] = None
    installation_key: Optional[str] = None
    status: Optional[
        Literal[
            "configuration_required",
            "installing",
            "connected",
            "binding",
            "tools_bound",
            "binding_skipped",
            "failed",
        ]
    ] = None
    mcp_id: Optional[int] = None
    discovered_tool_ids: List[int] = Field(default_factory=list)
    bound_tool_ids: List[int] = Field(default_factory=list)
    binding_operation_id: Optional[str] = None
    error: Optional[str] = None


class CardDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: int = Field(ge=1)
    card_type: CardType
    status: Literal["rendered", "failed"]
    card_key: Optional[str] = None
    reason: Optional[str] = None
    retry_count: int = Field(default=0, ge=0)


class Nl2AgentWorkflowState(BaseModel):
    """Redis-persisted workflow state. Old schemas are intentionally rejected."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = WORKFLOW_SCHEMA_VERSION
    revision: int = Field(default=0, ge=0)
    conversation_id: int = Field(ge=1)
    requirements_review: RequirementsReview = Field(default_factory=RequirementsReview)
    model_selection_confirmed: bool = False
    trusted_search_batches: Dict[str, TrustedSearchBatch] = Field(default_factory=dict)
    recommendation_batches: Dict[str, RecommendationBatch] = Field(default_factory=dict)
    identity_confirmed: bool = False
    mcp_workflows: Dict[str, McpWorkflow] = Field(default_factory=dict)
    online_recommendation_batches: Dict[str, OnlineRecommendationBatch] = Field(
        default_factory=dict
    )
    online_installations: Dict[str, OnlineInstallation] = Field(default_factory=dict)
    online_configuration_confirmed: bool = False
    card_delivery: Dict[CardType, CardDelivery] = Field(default_factory=dict)

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
    allowed_actions: List[str]
    requirements_status: str
    model_selection_confirmed: bool
    local_review_status: Literal["missing", "pending", "complete"]
    mcp_batch_registered: bool
    skill_batch_registered: bool
    online_configuration_confirmed: bool
    unresolved_mcp_count: int
    identity_confirmed: bool


def _card_was_rendered(state: Nl2AgentWorkflowState, card_type: CardType) -> bool:
    receipt = state.card_delivery.get(card_type)
    return receipt is not None and receipt.status == "rendered"


@dataclass(frozen=True)
class _WorkflowFacts:
    local_status: Literal["missing", "pending", "complete"]
    mcp_registered: bool
    skill_registered: bool
    unresolved_mcp_count: int

    @property
    def all_online_registered(self) -> bool:
        return self.mcp_registered and self.skill_registered


@dataclass(frozen=True)
class _StageDecision:
    stage: WorkflowStage
    expected: List[CardType]
    allowed: List[str]


def _workflow_facts(state: Nl2AgentWorkflowState) -> _WorkflowFacts:
    local_batches = list(state.recommendation_batches.values())
    if not local_batches:
        local_status: Literal["missing", "pending", "complete"] = "missing"
    elif any(
        batch.status in {"recommendations_ready", "applying"}
        for batch in local_batches
    ):
        local_status = "pending"
    else:
        local_status = "complete"

    online_types = {
        batch.resource_type for batch in state.online_recommendation_batches.values()
    }
    return _WorkflowFacts(
        local_status=local_status,
        mcp_registered="mcp" in online_types,
        skill_registered="skill" in online_types,
        unresolved_mcp_count=sum(
            workflow.status in {"installing", "connected", "binding"}
            for workflow in state.mcp_workflows.values()
        ),
    )


def _unrendered_cards(
    state: Nl2AgentWorkflowState,
    *card_types: CardType,
) -> List[CardType]:
    return [
        card_type
        for card_type in card_types
        if not _card_was_rendered(state, card_type)
    ]


def _select_stage(
    state: Nl2AgentWorkflowState,
    facts: _WorkflowFacts,
) -> _StageDecision:
    requirements_status = state.requirements_review.status
    if requirements_status == "collecting":
        return _StageDecision(
            "requirements_collecting",
            [],
            ["clarify_requirements", "render_requirements_summary"],
        )
    if requirements_status == "awaiting_confirmation":
        return _StageDecision(
            "requirements_confirmation",
            _unrendered_cards(state, "requirements_summary"),
            ["confirm_requirements", "revise_requirements"],
        )
    if not state.model_selection_confirmed:
        return _StageDecision(
            "model_selection",
            _unrendered_cards(state, "model_selection"),
            ["select_models"],
        )
    if facts.local_status == "missing":
        return _StageDecision(
            "local_resource_search",
            ["local_resources"],
            ["search_local_resources"],
        )
    if facts.local_status == "pending":
        return _StageDecision(
            "local_resource_review",
            _unrendered_cards(state, "local_resources"),
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
        return _StageDecision("online_resource_search", expected, allowed)
    if not state.online_configuration_confirmed:
        return _StageDecision(
            "online_resource_review",
            _unrendered_cards(state, "web_mcp", "web_skill"),
            ["configure_online_resources", "complete_online_configuration"],
        )
    if not state.identity_confirmed:
        return _StageDecision(
            "agent_identity",
            _unrendered_cards(state, "agent_identity"),
            ["save_identity"],
        )
    return _StageDecision(
        "final_review",
        _unrendered_cards(state, "final_review"),
        ["publish_agent"],
    )


def evaluate_workflow(state: Nl2AgentWorkflowState) -> WorkflowSummary:
    """Return the single authoritative next stage for a persisted state."""
    facts = _workflow_facts(state)
    decision = _select_stage(state, facts)

    return WorkflowSummary(
        current_stage=decision.stage,
        expected_card_types=decision.expected,
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
