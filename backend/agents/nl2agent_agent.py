"""Build the ephemeral NL2Agent and its MCP tool configuration."""

from copy import deepcopy
import json
import keyword
import re
from typing import Annotated, Any, Literal

from jinja2 import StrictUndefined, Template
from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from pydantic import BaseModel, ConfigDict, Field, model_validator

from consts.const import LANGUAGE
from utils.prompt_template_utils import get_prompt_template

NL2AGENT_NAME = "__nl2agent_runtime__"
MAX_TOOL_RECOMMENDATIONS = 5
FEW_SHOT_EXAMPLE_COUNT = 2
NL2A_SUBTYPES = Literal["local_mcp_recommendation", "agent_draft"]

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

    if subtype == "local_mcp_recommendation":
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


def build_nl2agent_system_prompt(
    language: str,
    tool_name: str | None = None,
    wrapper_name: str | None = None,
    max_results: int = MAX_TOOL_RECOMMENDATIONS,
) -> str:
    """Load and render the localized NL2Agent system prompt."""

    from tool_collection.mcp.nl2agent_mcp_tools import (
        NL2A_WRAPPER_NAME,
        SEARCH_INSTALLED_MCP_TOOLS_NAME,
    )

    if tool_name is None:
        tool_name = SEARCH_INSTALLED_MCP_TOOLS_NAME
    if wrapper_name is None:
        wrapper_name = NL2A_WRAPPER_NAME

    template_language = (
        LANGUAGE["EN"] if language == LANGUAGE["EN"] else LANGUAGE["ZH"]
    )
    template = get_prompt_template("nl2agent", template_language)["system_prompt"]
    return Template(template, undefined=StrictUndefined).render(
        tool_name=tool_name,
        wrapper_name=wrapper_name,
        max_results=max_results,
    )


def create_nl2agent_agent_config(language: str) -> AgentConfig:
    """Create the in-memory AgentConfig for one NL2Agent request."""

    from tool_collection.mcp.local_mcp_service import (
        get_nl2agent_mcp_tool_descriptions,
    )
    from tool_collection.mcp.nl2agent_mcp_tools import (
        NL2A_WRAPPER_NAME,
        SEARCH_INSTALLED_MCP_TOOLS_NAME,
    )

    tool_descriptions = get_nl2agent_mcp_tool_descriptions()
    search_tool_config = ToolConfig(
        class_name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
        name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
        description=tool_descriptions[SEARCH_INSTALLED_MCP_TOOLS_NAME],
        inputs='{"keywords": "list[str]"}',
        output_type="object",
        params={},
        source="mcp",
        usage="outer-apis",
    )
    wrapper_tool_config = ToolConfig(
        class_name=NL2A_WRAPPER_NAME,
        name=NL2A_WRAPPER_NAME,
        description=tool_descriptions[NL2A_WRAPPER_NAME],
        inputs=json.dumps(
            {
                "subtype": "str",
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
    )

    return AgentConfig(
        name=NL2AGENT_NAME,
        description="Ephemeral natural-language agent builder",
        prompt_templates=None,
        tools=[search_tool_config, wrapper_tool_config],
        max_steps=5,
        model_name="main_model",
        provide_run_summary=False,
        instructions=build_nl2agent_system_prompt(language),
        enable_planning=False,
    )
