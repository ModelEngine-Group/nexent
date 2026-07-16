"""Typed NL2AGENT workflow state and deterministic stage evaluation."""

from __future__ import annotations

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

    status: Literal["recommendations_ready", "applied", "skipped"]
    tool_ids: List[int] = Field(default_factory=list)
    skill_ids: List[int] = Field(default_factory=list)
    applied_tool_ids: List[int] = Field(default_factory=list)
    applied_skill_ids: List[int] = Field(default_factory=list)


class OnlineRecommendationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: Literal["mcp", "skill"]
    item_keys: List[str] = Field(default_factory=list)
    status: Literal["recommendations_ready", "completed"]


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
            "tools_bound",
            "binding_skipped",
            "failed",
        ]
    ] = None
    mcp_id: Optional[int] = None
    discovered_tool_ids: List[int] = Field(default_factory=list)
    bound_tool_ids: List[int] = Field(default_factory=list)
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
    online_recommendation_batches: Dict[str, OnlineRecommendationBatch] = Field(default_factory=dict)
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


def evaluate_workflow(state: Nl2AgentWorkflowState) -> WorkflowSummary:
    """Return the single authoritative next stage for a persisted state."""
    requirements_status = state.requirements_review.status
    local_batches = list(state.recommendation_batches.values())
    if not local_batches:
        local_status: Literal["missing", "pending", "complete"] = "missing"
    elif any(batch.status == "recommendations_ready" for batch in local_batches):
        local_status = "pending"
    else:
        local_status = "complete"

    online_types = {batch.resource_type for batch in state.online_recommendation_batches.values()}
    mcp_registered = "mcp" in online_types
    skill_registered = "skill" in online_types
    unresolved_mcp_count = sum(
        workflow.status in {"installing", "connected"} for workflow in state.mcp_workflows.values()
    )

    expected: List[CardType] = []
    allowed: List[str] = []
    if requirements_status == "collecting":
        stage: WorkflowStage = "requirements_collecting"
        allowed = ["clarify_requirements", "render_requirements_summary"]
    elif requirements_status == "awaiting_confirmation":
        stage = "requirements_confirmation"
        if not _card_was_rendered(state, "requirements_summary"):
            expected = ["requirements_summary"]
        allowed = ["confirm_requirements", "revise_requirements"]
    elif not state.model_selection_confirmed:
        stage = "model_selection"
        if not _card_was_rendered(state, "model_selection"):
            expected = ["model_selection"]
        allowed = ["select_models"]
    elif local_status == "missing":
        stage = "local_resource_search"
        expected = ["local_resources"]
        allowed = ["search_local_resources"]
    elif local_status == "pending":
        stage = "local_resource_review"
        if not _card_was_rendered(state, "local_resources"):
            expected = ["local_resources"]
        allowed = ["apply_local_resources", "skip_local_resources"]
    elif not (mcp_registered and skill_registered):
        stage = "online_resource_search"
        if not mcp_registered:
            expected.append("web_mcp")
        if not skill_registered:
            expected.append("web_skill")
        allowed = ["search_online_resources"]
    elif not state.online_configuration_confirmed:
        stage = "online_resource_review"
        if not _card_was_rendered(state, "web_mcp"):
            expected.append("web_mcp")
        if not _card_was_rendered(state, "web_skill"):
            expected.append("web_skill")
        allowed = ["configure_online_resources", "complete_online_configuration"]
    elif not state.identity_confirmed:
        stage = "agent_identity"
        if not _card_was_rendered(state, "agent_identity"):
            expected = ["agent_identity"]
        allowed = ["save_identity"]
    else:
        stage = "final_review"
        if not _card_was_rendered(state, "final_review"):
            expected = ["final_review"]
        allowed = ["publish_agent"]

    return WorkflowSummary(
        current_stage=stage,
        expected_card_types=expected,
        allowed_actions=allowed,
        requirements_status=requirements_status,
        model_selection_confirmed=state.model_selection_confirmed,
        local_review_status=local_status,
        mcp_batch_registered=mcp_registered,
        skill_batch_registered=skill_registered,
        online_configuration_confirmed=state.online_configuration_confirmed,
        unresolved_mcp_count=unresolved_mcp_count,
        identity_confirmed=state.identity_confirmed,
    )


def state_to_dict(state: Nl2AgentWorkflowState) -> Dict[str, Any]:
    return state.model_dump(mode="json")
