"""Canonical Pydantic contract for structured NL2AGENT card messages."""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any, Dict, List, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


NL2AGENT_CARD_SCHEMA_VERSION = 1
NL2AGENT_CARD_SCHEMA_ID = "https://nexent.dev/contracts/nl2agent-card.schema.json"
NL2AGENT_CARD_TYPES = (
    "requirements_summary",
    "model_selection",
    "local_resources",
    "web_mcp",
    "web_skill",
    "agent_identity",
    "final_review",
)

PositiveInt = Annotated[int, Field(strict=True, ge=1)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
NonEmptyString = Annotated[str, Field(min_length=1)]
BatchIdentifier = Annotated[str, Field(min_length=1, max_length=128)]
CardKey = Annotated[str, Field(min_length=1, max_length=128)]
Score = Annotated[float, Field(strict=True, ge=0, le=1)]


class _StrictCardModel(BaseModel):
    """Reject undeclared or coercible values in persisted card metadata."""

    model_config = ConfigDict(extra="forbid", strict=True)


class _AgentScopedPayload(_StrictCardModel):
    agent_id: PositiveInt = Field(default=None)


class Nl2AgentRequirementsSummaryCardPayload(_AgentScopedPayload):
    goal: str = Field(min_length=1, max_length=500)
    audience_or_scenario: str = Field(min_length=1, max_length=500)
    primary_input: str = Field(min_length=1, max_length=1000)
    expected_output: str = Field(min_length=1, max_length=1000)
    key_constraints: str = Field(min_length=1, max_length=2000)


class Nl2AgentModelSelectionCardPayload(_AgentScopedPayload):
    pass


class Nl2AgentLocalToolCardItem(_StrictCardModel):
    tool_id: PositiveInt
    name: NonEmptyString
    description: str = Field(default=None)
    labels: List[str] = Field(default=None)
    source: str = Field(default=None)
    category: str = Field(default=None)
    usage: str = Field(default=None)
    score: Score = Field(default=None)
    reason: str = Field(default=None)


class Nl2AgentLocalSkillCardItem(_StrictCardModel):
    skill_id: PositiveInt
    name: NonEmptyString
    description: str = Field(default=None)
    tags: List[str] = Field(default=None)
    score: Score = Field(default=None)
    reason: str = Field(default=None)


class Nl2AgentLocalResourcesCardPayload(_AgentScopedPayload):
    recommendation_batch_id: BatchIdentifier
    tools: List[Nl2AgentLocalToolCardItem] = Field(max_length=100)
    skills: List[Nl2AgentLocalSkillCardItem] = Field(max_length=100)


class Nl2AgentMcpField(_StrictCardModel):
    key: NonEmptyString
    name: NonEmptyString
    label: str = Field(default=None)
    description: str = Field(default=None)
    type: Literal["text", "number", "url", "json"]
    required: bool
    secret: bool
    default: Union[str, int, float, bool, None] = None
    placeholder: str = Field(default=None)
    choices: List[str] = Field(default=None)
    category: str = Field(default=None)
    argument_type: Literal["named", "positional"] = Field(default=None)
    argument_name: str | None = None
    repeated: bool = Field(default=None)


class Nl2AgentMcpInstallOption(_StrictCardModel):
    option_id: NonEmptyString
    type: Literal["remote", "container", "unsupported"]
    transport: str | None = None
    server_url_template: str | None = None
    requires_configuration: bool
    label: NonEmptyString
    description: str = Field(default=None)
    status: Literal["ready", "configuration_required", "unsupported"]
    supported: bool
    unsupported_reason: str = Field(default=None)
    package_identifier: str | None = None
    registry_type: str | None = None
    runtime_hint: str | None = None
    fields: List[Nl2AgentMcpField] = Field(max_length=100)


class Nl2AgentWebMcpCardItem(_AgentScopedPayload):
    recommendation_batch_id: BatchIdentifier = Field(default=None)
    recommendation_id: NonEmptyString
    name: NonEmptyString
    description: str = Field(default=None)
    tags: List[str] = Field(default=None)
    source: Literal["registry", "community"] = Field(default=None)
    transport: str | None = None
    score: Score = Field(default=None)
    reason: str = Field(default=None)
    install_options: List[Nl2AgentMcpInstallOption] = Field(min_length=1, max_length=20)


class Nl2AgentWebMcpSingleCardPayload(Nl2AgentWebMcpCardItem):
    recommendation_batch_id: BatchIdentifier


class Nl2AgentWebMcpListCardPayload(_AgentScopedPayload):
    recommendation_batch_id: BatchIdentifier
    items: List[Nl2AgentWebMcpCardItem] = Field(max_length=100)


Nl2AgentWebMcpCardPayload = Union[
    Nl2AgentWebMcpListCardPayload,
    Nl2AgentWebMcpSingleCardPayload,
]


class Nl2AgentWebSkillCardItem(_AgentScopedPayload):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "allOf": [
                {"anyOf": [{"required": ["name"]}, {"required": ["skill_name"]}]},
                {
                    "anyOf": [
                        {"required": ["skill_id"]},
                        {"required": ["skill_name"]},
                    ]
                },
            ]
        },
    )

    recommendation_batch_id: BatchIdentifier = Field(default=None)
    skill_id: PositiveInt = Field(default=None)
    skill_name: NonEmptyString = Field(default=None)
    name: NonEmptyString = Field(default=None)
    description: str = Field(default=None)
    tags: List[str] = Field(default=None)
    source: str = Field(default=None)
    status: str = Field(default=None)
    score: Score = Field(default=None)
    reason: str = Field(default=None)

    @model_validator(mode="after")
    def validate_stable_identity(self) -> "Nl2AgentWebSkillCardItem":
        if not self.name and not self.skill_name:
            raise ValueError("A web Skill card item requires a display name.")
        if self.skill_id is None and not self.skill_name:
            raise ValueError("A web Skill card item requires a stable identifier.")
        return self


class Nl2AgentWebSkillSingleCardPayload(Nl2AgentWebSkillCardItem):
    recommendation_batch_id: BatchIdentifier


class Nl2AgentWebSkillListCardPayload(_AgentScopedPayload):
    recommendation_batch_id: BatchIdentifier
    items: List[Nl2AgentWebSkillCardItem] = Field(max_length=100)


Nl2AgentWebSkillCardPayload = Union[
    Nl2AgentWebSkillListCardPayload,
    Nl2AgentWebSkillSingleCardPayload,
]


class Nl2AgentAgentIdentityCardPayload(_AgentScopedPayload):
    display_name: str = Field(min_length=1, max_length=50)


class Nl2AgentVerificationConfig(_StrictCardModel):
    enabled: bool
    step_verification_enabled: bool = Field(default=None)
    final_verification_enabled: bool = Field(default=None)
    llm_verification_enabled: bool = Field(default=None)
    max_final_rounds: int = Field(default=None, ge=1, le=5)
    strictness: Literal["lenient", "balanced", "strict"] = Field(default=None)
    fail_policy: Literal["repair_then_controlled_summary", "warn"] = Field(default=None)
    pass_score: Score = Field(default=None)
    critical_events: List[
        Literal[
            "tool_precheck",
            "tool_result",
            "retrieval",
            "code_execution",
            "handoff",
            "final_answer",
        ]
    ] = Field(default=None)


class Nl2AgentFinalReviewCardPayload(_AgentScopedPayload):
    description: str = Field(default=None, max_length=500)
    business_description: str = Field(min_length=1, max_length=2000)
    duty_prompt: str = Field(min_length=1, max_length=8000)
    constraint_prompt: str = Field(default=None, max_length=4000)
    few_shots_prompt: str = Field(default=None, max_length=8000)
    greeting_message: str = Field(min_length=1, max_length=500)
    example_questions: List[Annotated[str, Field(max_length=500)]] = Field(
        default=None, max_length=6
    )
    max_steps: int = Field(default=None, ge=1, le=30)
    requested_output_tokens: PositiveInt = Field(default=None)
    provide_run_summary: bool = Field(default=None)
    verification_config: Nl2AgentVerificationConfig = Field(default=None)
    enable_context_manager: bool = Field(default=None)


class Nl2AgentRequirementsSummaryCard(_StrictCardModel):
    card_type: Literal["requirements_summary"]
    card_key: Literal["requirements_summary"]
    payload: Nl2AgentRequirementsSummaryCardPayload


class Nl2AgentModelSelectionCard(_StrictCardModel):
    card_type: Literal["model_selection"]
    card_key: Literal["model_selection"]
    payload: Nl2AgentModelSelectionCardPayload


class _RecommendationCard(_StrictCardModel):
    card_key: CardKey

    def _validate_batch_key(self, recommendation_batch_id: str) -> None:
        if self.card_key != recommendation_batch_id:
            raise ValueError("card_key must equal the recommendation batch identifier.")


class Nl2AgentLocalResourcesCard(_RecommendationCard):
    card_type: Literal["local_resources"]
    payload: Nl2AgentLocalResourcesCardPayload

    @model_validator(mode="after")
    def validate_card_key(self) -> "Nl2AgentLocalResourcesCard":
        self._validate_batch_key(self.payload.recommendation_batch_id)
        return self


class Nl2AgentWebMcpCard(_RecommendationCard):
    card_type: Literal["web_mcp"]
    payload: Nl2AgentWebMcpCardPayload

    @model_validator(mode="after")
    def validate_card_key(self) -> "Nl2AgentWebMcpCard":
        self._validate_batch_key(self.payload.recommendation_batch_id)
        return self


class Nl2AgentWebSkillCard(_RecommendationCard):
    card_type: Literal["web_skill"]
    payload: Nl2AgentWebSkillCardPayload

    @model_validator(mode="after")
    def validate_card_key(self) -> "Nl2AgentWebSkillCard":
        self._validate_batch_key(self.payload.recommendation_batch_id)
        return self


class Nl2AgentAgentIdentityCard(_StrictCardModel):
    card_type: Literal["agent_identity"]
    card_key: Literal["agent_identity"]
    payload: Nl2AgentAgentIdentityCardPayload


class Nl2AgentFinalReviewCard(_StrictCardModel):
    card_type: Literal["final_review"]
    card_key: Literal["final_review"]
    payload: Nl2AgentFinalReviewCardPayload


Nl2AgentCard = Annotated[
    Union[
        Nl2AgentRequirementsSummaryCard,
        Nl2AgentModelSelectionCard,
        Nl2AgentLocalResourcesCard,
        Nl2AgentWebMcpCard,
        Nl2AgentWebSkillCard,
        Nl2AgentAgentIdentityCard,
        Nl2AgentFinalReviewCard,
    ],
    Field(discriminator="card_type"),
]


class Nl2AgentCardEnvelope(_StrictCardModel):
    """Persisted cards and their authoritative Session revision."""

    schema_version: Literal[1]
    draft_agent_id: PositiveInt
    workflow_revision: NonNegativeInt
    cards: List[Nl2AgentCard] = Field(max_length=7)

    @model_validator(mode="after")
    def validate_card_scope(self) -> "Nl2AgentCardEnvelope":
        card_types = [card.card_type for card in self.cards]
        card_keys = [card.card_key for card in self.cards]
        if len(set(card_types)) != len(card_types):
            raise ValueError("An NL2AGENT message cannot repeat a card type.")
        if len(set(card_keys)) != len(card_keys):
            raise ValueError("An NL2AGENT message cannot repeat a card key.")
        for card in self.cards:
            payload = card.payload
            candidate_ids = []
            if payload.agent_id is not None:
                candidate_ids.append(payload.agent_id)
            for item in getattr(payload, "items", []) or []:
                if item.agent_id is not None:
                    candidate_ids.append(item.agent_id)
            if any(candidate != self.draft_agent_id for candidate in candidate_ids):
                raise ValueError("Card payload agent_id does not match draft_agent_id.")
        return self


def _payload_aliases(
    definitions: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    return {
        "requirements_summary": deepcopy(
            definitions["Nl2AgentRequirementsSummaryCardPayload"]
        ),
        "model_selection": deepcopy(definitions["Nl2AgentModelSelectionCardPayload"]),
        "local_resources": deepcopy(definitions["Nl2AgentLocalResourcesCardPayload"]),
        "web_mcp": {
            "oneOf": [
                {"$ref": "#/$defs/Nl2AgentWebMcpListCardPayload"},
                {"$ref": "#/$defs/Nl2AgentWebMcpSingleCardPayload"},
            ]
        },
        "web_skill": {
            "oneOf": [
                {"$ref": "#/$defs/Nl2AgentWebSkillListCardPayload"},
                {"$ref": "#/$defs/Nl2AgentWebSkillSingleCardPayload"},
            ]
        },
        "agent_identity": deepcopy(definitions["Nl2AgentAgentIdentityCardPayload"]),
        "final_review": deepcopy(definitions["Nl2AgentFinalReviewCardPayload"]),
    }


def build_nl2agent_card_schema() -> Dict[str, Any]:
    """Generate the standalone JSON Schema from the Pydantic contract."""
    schema = Nl2AgentCardEnvelope.model_json_schema(ref_template="#/$defs/{model}")
    definitions = schema.setdefault("$defs", {})
    definitions.update(_payload_aliases(definitions))

    envelope_properties = schema["properties"]
    local_properties = definitions["Nl2AgentLocalResourcesCardPayload"]["properties"]
    tool_properties = definitions["Nl2AgentLocalToolCardItem"]["properties"]
    definitions.update(
        {
            "positiveInteger": _without_annotation_metadata(
                envelope_properties["draft_agent_id"]
            ),
            "nonEmptyString": _without_annotation_metadata(tool_properties["name"]),
            "batchIdentifier": _without_annotation_metadata(
                local_properties["recommendation_batch_id"]
            ),
            "stringArray": _without_annotation_metadata(tool_properties["labels"]),
            "score": _without_annotation_metadata(tool_properties["score"]),
        }
    )
    schema.update(
        {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "$id": NL2AGENT_CARD_SCHEMA_ID,
            "title": "NL2AGENT card envelope",
        }
    )
    return schema


def _without_annotation_metadata(value: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(value)
    result.pop("default", None)
    result.pop("title", None)
    return result


CARD_PAYLOAD_MODELS = {
    "requirements_summary": Nl2AgentRequirementsSummaryCardPayload,
    "model_selection": Nl2AgentModelSelectionCardPayload,
    "local_resources": Nl2AgentLocalResourcesCardPayload,
    "web_mcp": Nl2AgentWebMcpCardPayload,
    "web_skill": Nl2AgentWebSkillCardPayload,
    "agent_identity": Nl2AgentAgentIdentityCardPayload,
    "final_review": Nl2AgentFinalReviewCardPayload,
}

CARD_MODELS = {
    "requirements_summary": Nl2AgentRequirementsSummaryCard,
    "model_selection": Nl2AgentModelSelectionCard,
    "local_resources": Nl2AgentLocalResourcesCard,
    "web_mcp": Nl2AgentWebMcpCard,
    "web_skill": Nl2AgentWebSkillCard,
    "agent_identity": Nl2AgentAgentIdentityCard,
    "final_review": Nl2AgentFinalReviewCard,
}
