"""Define and implement the internal Local MCP tools used by NL2Agent."""

from copy import deepcopy
import json
import keyword
import logging
import re
import unicodedata
from typing import Annotated, Any, Literal

from fastmcp.server.dependencies import get_http_request
from nexent.core.agents.agent_model import ToolConfig
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)

SEARCH_INSTALLED_MCP_TOOLS_NAME = "search_installed_mcp_tools"
SEARCH_INSTALLED_RESOURCES_NAME = "search_installed_resources"
SEARCH_UNINSTALLED_RESOURCES_NAME = "search_uninstalled_resources"
RECOMMEND_RESOURCES_NAME = "recommend_resources"
SAVE_AGENT_DRAFT_FIELDS_NAME = "save_agent_draft_fields"
NL2A_WRAPPER_NAME = "nl2a_wrapper"
SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION = (
    "Search the current tenant's installed and available MCP tools using keywords. "
    "Returns a structured JSON observation ordered by relevance. "
    "Call the tool as `result = search_installed_mcp_tools(...)`, then use "
    "`print(result)` to preserve the returned JSON unchanged in execution logs."
)
NL2A_WRAPPER_DESCRIPTION = (
    "Build one NL2Agent output from subtype-specific parameters. Always pass "
    "`subtype`. For `requirement_clarification`, pass structured `questions`. "
    "For `local_mcp_recommendation`, also pass `search_result` and "
    "`selected_tool_ids`. For `agent_draft`, pass the agent draft fields. Call "
    "the tool as `result = nl2a_wrapper(...)`, then use `print(result)`."
)
SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION = (
    "Create or partially update the current tenant's ordinary agent draft. "
    "Pass only whitelisted fields, never null. Creation requires name, "
    "display_name, description, and business_description. Call the tool as "
    "`result = save_agent_draft_fields(...)`, then use `print(result)` exactly once."
)
NL2AGENT_MCP_TOOL_META = {"nexent_internal": True}
MAX_TOOL_RECOMMENDATIONS = 5
MAX_REQUIREMENT_CLARIFICATION_QUESTIONS = 5
FEW_SHOT_EXAMPLE_COUNT = 2
NL2A_SUBTYPES = Literal[
    "requirement_clarification",
    "local_mcp_recommendation",
    "agent_draft",
]

LOCAL_MCP_RECOMMENDATION_JSON_TEMPLATE: dict[str, Any] = {
    "subtype": "local_mcp_recommendation",
    "status": "success",
    "recommendation_count": 0,
    "recommendations": [],
}

AGENT_DRAFT_JSON_TEMPLATE: dict[str, Any] = {
    "subtype": "agent_draft",
    "name": "",
    "display_name": "",
    "description": "",
    "duty_prompt": "",
    "constraint_prompt": "",
    "few_shots_prompt": None,
    "greeting_message": "",
    "example_questions": [],
}


class ResourceRequirement(BaseModel):
    """One capability requirement shared by the phase-two search tools."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    requirement_id: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=500)
    resource_name_hint: str | None = Field(default=None, max_length=200)
    search_terms: list[str] = Field(default_factory=list, max_length=10)


class ResourceCandidate(BaseModel):
    """Frozen common output boundary for resource discovery."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_ref: str = Field(min_length=1)
    resource_type: Literal["tool", "skill", "mcp_server"]
    source: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    requirement_ids: list[str] = Field(min_length=1)
    score: float = Field(ge=0, le=1)


class SearchInstalledResourcesInput(BaseModel):
    """Frozen input for installed Tool/Skill discovery (implemented in PR2)."""

    model_config = ConfigDict(extra="forbid")
    requirements: list[ResourceRequirement] = Field(min_length=1, max_length=8)


class SearchUninstalledResourcesInput(BaseModel):
    """Frozen input for internal or official-registry discovery (PR2)."""

    model_config = ConfigDict(extra="forbid")
    requirements: list[ResourceRequirement] = Field(min_length=1, max_length=8)
    scope: Literal["internal", "external_registry"]
    exclude_refs: list[str] = Field(default_factory=list, max_length=100)


class ResourceSearchOutput(BaseModel):
    """Frozen successful output shared by both resource search tools."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["success"] = "success"
    candidates: list[ResourceCandidate]
    uncovered_requirement_ids: list[str]


class RecommendResourcesInput(BaseModel):
    """Frozen input for resolving selected candidates into card data (PR2)."""

    model_config = ConfigDict(extra="forbid")
    candidate_refs: list[str] = Field(min_length=1, max_length=12)
    recommended_refs: list[str] = Field(default_factory=list, max_length=12)


class RecommendedResource(BaseModel):
    """Frozen card-facing resource detail boundary (implemented in PR2)."""

    model_config = ConfigDict(extra="forbid")
    candidate: ResourceCandidate
    recommendation: Literal["recommended", "optional"]
    form_kind: Literal[
        "TOOL_CONFIG",
        "SKILL_CONFIG",
        "MCP_REMOTE",
        "MCP_PACKAGE",
        "MCP_CONTAINER",
    ]
    config: dict[str, Any] | list[dict[str, Any]]


class RecommendResourcesOutput(BaseModel):
    """Frozen successful recommend-resources output (implemented in PR2)."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["success"] = "success"
    resources: list[RecommendedResource]


class AgentDraftFields(BaseModel):
    """Whitelisted partial fields accepted by the database draft tool."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=100)
    display_name: str | None = Field(default=None, max_length=100)
    description: str | None = None
    business_description: str | None = None
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
    """Frozen input model for create-or-update draft persistence."""

    model_config = ConfigDict(extra="forbid")
    agent_id: int | None = Field(default=None, gt=0)
    fields: AgentDraftFields


class SaveAgentDraftFieldsSuccess(BaseModel):
    """Stable success result returned by save_agent_draft_fields."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["success"] = "success"
    agent_id: int = Field(gt=0)
    created: bool
    updated_fields: list[str]


class SaveAgentDraftFieldsError(BaseModel):
    """Stable non-sensitive error returned by save_agent_draft_fields."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["error"] = "error"
    agent_id: int | None = None
    created: Literal[False] = False
    updated_fields: list[str] = Field(default_factory=list)
    code: Literal[
        "invalid_agent_fields",
        "basic_fields_required",
        "default_model_missing",
        "agent_not_found",
        "agent_not_draft",
        "agent_deleted",
        "agent_read_only",
        "draft_save_failed",
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
    agent_id: None = None
    questions: list[RequirementClarificationQuestion] = Field(
        min_length=1,
        max_length=MAX_REQUIREMENT_CLARIFICATION_QUESTIONS,
    )


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


class GeneratedAgentDraft(BaseModel):
    """Complete in-memory agent draft for the agent creation flow."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subtype: Literal["agent_draft"] = "agent_draft"
    name: str = Field(min_length=1, max_length=30)
    display_name: str = Field(min_length=1, max_length=30)
    description: str = Field(min_length=1)
    duty_prompt: str = Field(min_length=1)
    constraint_prompt: str
    few_shots_prompt: str | None = None
    greeting_message: str = Field(min_length=1)
    example_questions: list[str] = Field(min_length=3, max_length=5)


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


class Nl2aFewShotToolCall(BaseModel):
    """One selected-tool call rendered into an agent few-shot example."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1)
    arguments: dict[str, Any]

    @model_validator(mode="after")
    def validate_python_names(self) -> "Nl2aFewShotToolCall":
        if not self.name.isidentifier() or keyword.iskeyword(self.name):
            raise ValueError("tool call name must be a valid Python identifier")
        if any(
            not name.isidentifier() or keyword.iskeyword(name)
            for name in self.arguments
        ):
            raise ValueError("tool argument names must be valid Python identifiers")
        return self


class Nl2aFewShotStep(BaseModel):
    """One Think-Code-Observation step in a structured few-shot example."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reasoning: str = Field(min_length=1)
    tool_calls: list[Nl2aFewShotToolCall] = Field(min_length=1)
    observation: str = Field(min_length=1)


class Nl2aFewShotExample(BaseModel):
    """Structured few-shot content that contains no executable code tags."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_input: str = Field(min_length=1)
    steps: list[Nl2aFewShotStep] = Field(min_length=1)
    final_reasoning: str = Field(min_length=1)
    final_answer: str = Field(min_length=1)


Nl2aFewShotExamples = Annotated[
    list[Nl2aFewShotExample],
    Field(
        min_length=FEW_SHOT_EXAMPLE_COUNT,
        max_length=FEW_SHOT_EXAMPLE_COUNT,
        description="Exactly two structured few-shot examples.",
    ),
]


class Nl2aLocalMcpRecommendationInput(BaseModel):
    """Wrapper input for a real installed-tool search observation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subtype: Literal["local_mcp_recommendation"]
    search_result: dict[str, Any]
    selected_tool_ids: list[int] = Field(max_length=MAX_TOOL_RECOMMENDATIONS)

    @model_validator(mode="after")
    def validate_selected_tool_ids(self) -> "Nl2aLocalMcpRecommendationInput":
        if len(self.selected_tool_ids) != len(set(self.selected_tool_ids)):
            raise ValueError("selected_tool_ids must be unique")
        return self


class Nl2aAgentDraftInput(BaseModel):
    """Wrapper input used to validate and render a complete agent draft."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subtype: Literal["agent_draft"]
    language: Literal["en", "zh"]
    name: str = Field(min_length=1, max_length=30)
    display_name: str = Field(min_length=1, max_length=30)
    description: str = Field(min_length=1)
    duty_prompt: str = Field(min_length=1)
    constraint_prompt: str
    greeting_message: str = Field(min_length=1)
    example_questions: list[str] = Field(min_length=3, max_length=5)
    selected_tool_names: list[str] = Field(max_length=MAX_TOOL_RECOMMENDATIONS)
    few_shot_examples: Nl2aFewShotExamples | None = None

    @model_validator(mode="after")
    def validate_few_shot_tools(self) -> "Nl2aAgentDraftInput":
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*_assistant", self.name) is None:
            raise ValueError(
                "name must be a Python-compatible identifier ending with _assistant"
            )
        if self.language == "en":
            if not self.display_name.endswith("Assistant") or any(
                character.isspace() for character in self.display_name
            ):
                raise ValueError(
                    "English display_name must be one word ending with Assistant"
                )
        elif not self.display_name.endswith("助手"):
            raise ValueError("Chinese display_name must end with 助手")

        selected_names = set(self.selected_tool_names)
        if len(selected_names) != len(self.selected_tool_names):
            raise ValueError("selected_tool_names must be unique")
        if any(
            not name.isidentifier() or keyword.iskeyword(name)
            for name in selected_names
        ):
            raise ValueError("selected tool names must be valid Python identifiers")
        if selected_names and self.few_shot_examples is None:
            raise ValueError("few_shot_examples are required when tools are selected")
        if selected_names and not self.constraint_prompt:
            raise ValueError("constraint_prompt is required when tools are selected")
        if not selected_names and self.few_shot_examples is not None:
            raise ValueError("few_shot_examples require selected tools")
        if not selected_names and self.constraint_prompt:
            raise ValueError("constraint_prompt must be empty when no tools are selected")
        for example in self.few_shot_examples or []:
            unknown_names = {
                call.name
                for step in example.steps
                for call in step.tool_calls
            } - selected_names
            if unknown_names:
                raise ValueError(
                    "few-shot tool calls must use selected tool names: "
                    + ", ".join(sorted(unknown_names))
                )
        return self


def _render_few_shots(
    language: Literal["en", "zh"],
    few_shot_examples: Nl2aFewShotExamples | None,
) -> str | None:
    if few_shot_examples is None:
        return None

    rendered_examples: list[str] = []
    for example_index, example in enumerate(few_shot_examples, start=1):
        if language == "en":
            lines = [f'Task {example_index}: "{example.user_input}"']
        else:
            lines = [f'任务{example_index}："{example.user_input}"']

        for step_index, step in enumerate(example.steps, start=1):
            code_lines: list[str] = []
            multiple_calls = len(step.tool_calls) > 1
            for call_index, call in enumerate(step.tool_calls, start=1):
                variable_name = (
                    f"result_{step_index}_{call_index}"
                    if multiple_calls
                    else f"result_{step_index}"
                )
                arguments = ", ".join(
                    f"{name}={value!r}" for name, value in call.arguments.items()
                )
                code_lines.append(f"{variable_name} = {call.name}({arguments})")
                code_lines.append(f"print({variable_name})")

            think_label = "Think" if language == "en" else "思考"
            code_label = "Code" if language == "en" else "代码"
            observation_prefix = (
                "# System returns Observation"
                if language == "en"
                else "# 系统返回 Observation"
            )
            lines.extend(
                [
                    "",
                    f"{think_label}: {step.reasoning}",
                    "",
                    f"{code_label}:",
                    "<code>",
                    *code_lines,
                    "</code>",
                    "",
                    f"{observation_prefix}: {step.observation}",
                ]
            )

        think_label = "Think" if language == "en" else "思考"
        lines.extend(
            [
                "",
                f"{think_label}: {example.final_reasoning}",
                "",
                example.final_answer,
            ]
        )
        rendered_examples.append("\n".join(lines))
    return "\n\n---\n\n".join(rendered_examples)


def build_nl2a_wrapper(
    subtype: NL2A_SUBTYPES,
    questions: list[RequirementClarificationQuestion] | None = None,
    search_result: dict[str, Any] | None = None,
    selected_tool_ids: list[int] | None = None,
    language: Literal["en", "zh"] | None = None,
    name: str | None = None,
    display_name: str | None = None,
    description: str | None = None,
    duty_prompt: str | None = None,
    constraint_prompt: str | None = None,
    greeting_message: str | None = None,
    example_questions: list[str] | None = None,
    selected_tool_names: list[str] | None = None,
    few_shot_examples: Nl2aFewShotExamples | None = None,
) -> str:
    """Fill the JSON template selected by subtype and return its wrapper."""

    if subtype == "requirement_clarification":
        if questions is None:
            raise ValueError("requirement_clarification requires questions")
        output = RequirementClarificationPayload(
            questions=questions,
        ).model_dump(mode="json")
    elif subtype == "local_mcp_recommendation":
        if search_result is None or selected_tool_ids is None:
            raise ValueError(
                "local_mcp_recommendation requires search_result and selected_tool_ids"
            )
        payload = Nl2aLocalMcpRecommendationInput(
            subtype=subtype,
            search_result=search_result,
            selected_tool_ids=selected_tool_ids,
        )
        if payload.search_result.get("status") == "error":
            if payload.selected_tool_ids:
                raise ValueError("selected_tool_ids must be empty for a search error")
            observation = SearchInstalledMcpToolsErrorObservation.model_validate(
                payload.search_result
            )
            output = deepcopy(LOCAL_MCP_RECOMMENDATION_JSON_TEMPLATE)
            output.pop("recommendation_count")
            output.pop("recommendations")
            output.update(observation.model_dump(mode="json", exclude={"subtype"}))
        elif payload.search_result.get("status") == "success":
            observation = SearchInstalledMcpToolsObservation.model_validate(
                payload.search_result
            )
            selected_ids = set(payload.selected_tool_ids)
            available_ids = {
                recommendation.tool_id
                for recommendation in observation.recommendations
            }
            unknown_ids = selected_ids - available_ids
            if unknown_ids:
                raise ValueError(
                    "selected tool IDs are not present in search_result: "
                    + ", ".join(str(tool_id) for tool_id in sorted(unknown_ids))
                )
            recommendations = [
                recommendation
                for recommendation in observation.recommendations
                if recommendation.tool_id in selected_ids
            ]
            output = deepcopy(LOCAL_MCP_RECOMMENDATION_JSON_TEMPLATE)
            output.update(
                recommendation_count=len(recommendations),
                recommendations=[
                    recommendation.model_dump(mode="json")
                    for recommendation in recommendations
                ],
            )
        else:
            raise ValueError("search_result has an unsupported status")
    elif subtype == "agent_draft":
        required_parameters = {
            "language": language,
            "name": name,
            "display_name": display_name,
            "description": description,
            "duty_prompt": duty_prompt,
            "constraint_prompt": constraint_prompt,
            "greeting_message": greeting_message,
            "example_questions": example_questions,
            "selected_tool_names": selected_tool_names,
        }
        missing_parameters = [
            parameter
            for parameter, value in required_parameters.items()
            if value is None
        ]
        if missing_parameters:
            raise ValueError(
                "agent_draft requires parameters: " + ", ".join(missing_parameters)
            )
        payload = Nl2aAgentDraftInput(
            subtype=subtype,
            language=language,
            name=name,
            display_name=display_name,
            description=description,
            duty_prompt=duty_prompt,
            constraint_prompt=constraint_prompt,
            greeting_message=greeting_message,
            example_questions=example_questions,
            selected_tool_names=selected_tool_names,
            few_shot_examples=few_shot_examples,
        )
        draft = GeneratedAgentDraft(
            name=payload.name,
            display_name=payload.display_name,
            description=payload.description,
            duty_prompt=payload.duty_prompt,
            constraint_prompt=payload.constraint_prompt,
            few_shots_prompt=_render_few_shots(
                payload.language,
                payload.few_shot_examples,
            ),
            greeting_message=payload.greeting_message,
            example_questions=payload.example_questions,
        )
        output = deepcopy(AGENT_DRAFT_JSON_TEMPLATE)
        output.update(draft.model_dump(mode="json", exclude={"subtype"}))
    else:
        raise ValueError(f"unsupported nl2a subtype: {subtype}")

    serialized = json.dumps(
        output,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"<nl2a>\n{serialized}\n</nl2a>\nNL2A payload generated."


def create_nl2agent_mcp_tool_configs() -> list[ToolConfig]:
    """Create fresh SDK configs for the NL2Agent tools exposed in PR1."""
    return [
        ToolConfig(
            class_name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
            name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
            description=SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION,
            inputs='{"keywords": "list[str]"}',
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
                    "agent_id": "int | None",
                    "fields": {
                        field_name: field_type
                        for field_name, field_type in {
                            "name": "str",
                            "display_name": "str",
                            "description": "str",
                            "business_description": "str",
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
                    "questions": "list[RequirementClarificationQuestion] | None",
                    "search_result": "dict | None",
                    "selected_tool_ids": "list[int] | None",
                    "language": "str | None",
                    "name": "str | None",
                    "display_name": "str | None",
                    "description": "str | None",
                    "duty_prompt": "str | None",
                    "constraint_prompt": "str | None",
                    "greeting_message": "str | None",
                    "example_questions": "list[str] | None",
                    "selected_tool_names": "list[str] | None",
                    "few_shot_examples": "list[dict] with exactly 2 items | None",
                },
                separators=(",", ":"),
            ),
            output_type="string",
            params={},
            source="mcp",
            usage="outer-apis",
        ),
    ]


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


async def nl2a_wrapper(
    subtype: Literal[
        "requirement_clarification",
        "local_mcp_recommendation",
        "agent_draft",
    ],
    questions: list[RequirementClarificationQuestion] | None = None,
    search_result: dict[str, Any] | None = None,
    selected_tool_ids: list[int] | None = None,
    language: Literal["en", "zh"] | None = None,
    name: str | None = None,
    display_name: str | None = None,
    description: str | None = None,
    duty_prompt: str | None = None,
    constraint_prompt: str | None = None,
    greeting_message: str | None = None,
    example_questions: list[str] | None = None,
    selected_tool_names: list[str] | None = None,
    few_shot_examples: Nl2aFewShotExamples | None = None,
) -> str:
    """Return the NL2Agent JSON template selected by subtype in its wrapper."""

    return build_nl2a_wrapper(
        subtype=subtype,
        questions=questions,
        search_result=search_result,
        selected_tool_ids=selected_tool_ids,
        language=language,
        name=name,
        display_name=display_name,
        description=description,
        duty_prompt=duty_prompt,
        constraint_prompt=constraint_prompt,
        greeting_message=greeting_message,
        example_questions=example_questions,
        selected_tool_names=selected_tool_names,
        few_shot_examples=few_shot_examples,
    )


def _serialize_agent_draft_save_result(
    result: SaveAgentDraftFieldsSuccess | SaveAgentDraftFieldsError,
) -> str:
    payload = result.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if isinstance(result, SaveAgentDraftFieldsSuccess) and result.created:
        state = json.dumps(
            {"event": "agent_draft_created", "agent_id": result.agent_id},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return f"{serialized}\n<nl2a_state>{state}</nl2a_state>"
    return serialized


async def save_agent_draft_fields(
    agent_id: int | None,
    fields: dict[str, Any],
) -> str:
    """Validate and persist a tenant-scoped ordinary AgentInfo draft patch."""
    try:
        payload = SaveAgentDraftFieldsInput(agent_id=agent_id, fields=fields)
    except ValidationError:
        return _serialize_agent_draft_save_result(
            SaveAgentDraftFieldsError(
                agent_id=agent_id,
                code="invalid_agent_fields",
                retryable=False,
            )
        )

    try:
        from services.nl2agent_service import (
            Nl2AgentDraftSaveError,
            save_agent_draft_fields_impl,
        )

        authorization = get_http_request().headers.get("Authorization")
        user_id, tenant_id = get_current_user_id(authorization)
        result = save_agent_draft_fields_impl(
            agent_id=payload.agent_id,
            fields=payload.fields,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return _serialize_agent_draft_save_result(
            SaveAgentDraftFieldsSuccess.model_validate(result)
        )
    except Nl2AgentDraftSaveError as exc:
        return _serialize_agent_draft_save_result(
            SaveAgentDraftFieldsError(
                agent_id=payload.agent_id,
                code=exc.code,
                retryable=exc.retryable,
            )
        )
    except PermissionError:
        return _serialize_agent_draft_save_result(
            SaveAgentDraftFieldsError(
                agent_id=payload.agent_id,
                code="unauthorized",
                retryable=False,
            )
        )
    except Exception:
        logger.exception("Failed to save NL2Agent draft fields")
        return _serialize_agent_draft_save_result(
            SaveAgentDraftFieldsError(
                agent_id=payload.agent_id,
                code="draft_save_failed",
                retryable=True,
            )
        )
