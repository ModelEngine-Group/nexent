"""Build the ephemeral NL2Agent and its MCP tool configuration."""

from copy import deepcopy
import json
import keyword
import re
from typing import Any, Literal

from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from pydantic import BaseModel, ConfigDict, Field, model_validator

from consts.const import LANGUAGE

NL2AGENT_NAME = "__nl2agent_runtime__"
SEARCH_INSTALLED_MCP_TOOLS_NAME = "search_installed_mcp_tools"
NL2A_WRAPPER_NAME = "nl2a_wrapper"
MAX_TOOL_RECOMMENDATIONS = 5
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
    few_shot_examples: list[Nl2aFewShotExample] | None = Field(
        default=None,
        min_length=3,
        max_length=5,
    )

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


def _render_few_shots(payload: Nl2aAgentDraftInput) -> str | None:
    if payload.few_shot_examples is None:
        return None

    rendered_examples: list[str] = []
    for example_index, example in enumerate(payload.few_shot_examples, start=1):
        if payload.language == "en":
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

            think_label = "Think" if payload.language == "en" else "思考"
            code_label = "Code" if payload.language == "en" else "代码"
            observation_prefix = (
                "# System returns Observation"
                if payload.language == "en"
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

        think_label = "Think" if payload.language == "en" else "思考"
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
    few_shot_examples: list[Nl2aFewShotExample] | None = None,
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
            few_shots_prompt=_render_few_shots(payload),
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
    tool_name: str = SEARCH_INSTALLED_MCP_TOOLS_NAME,
    wrapper_name: str = NL2A_WRAPPER_NAME,
    max_results: int = MAX_TOOL_RECOMMENDATIONS,
) -> str:
    """Assemble the NL2Agent instructions for one ephemeral run."""

    if language == LANGUAGE["EN"]:
        sections = [
            """## Role
You are NL2Agent. You confirm the requested agent, recommend installed MCP tools, and generate an in-memory agent draft. The product flow handles persistence.""",
            f"""## State Workflow
1. Requirements discovery: identify the agent's role, capabilities, tasks, and expected results through concise conversation.
2. Requirements confirmation: present a concise requirement summary and ask the user to confirm it.
3. Tool search: after explicit requirement confirmation, execute `{tool_name}` with 1 to 10 unique capability keywords of at most 100 characters each.
4. Recommendation packaging: select up to {max_results} relevant candidates from the search Observation, then execute `{wrapper_name}` with subtype `local_mcp_recommendation`.
5. Tool selection: input shaped as {{"type":"nl2agent_tool_selection","tools":[]}} confirms the selected tools.
6. Draft packaging: build the complete draft from the confirmed requirements and selected tools, then execute `{wrapper_name}` with subtype `agent_draft`.
7. Completion: an Observation containing `NL2A payload generated.` transitions to one concise completion sentence.""",
            f"""## Confirmed Requirement Search
Thought: The requirements are confirmed. I will search for matching installed tools.
<code>
search_result = {tool_name}(keywords=["weather forecast", "travel advice"])
print(search_result)
</code>
The real Observation supplies the input for recommendation packaging. A successful empty Chinese search transitions to the same action with English capability keywords.""",
            """## Conversational States
Requirements discovery uses one concise question at a time. Requirements confirmation uses a concise summary and an explicit confirmation question.""",
            f"""## Tool Selection Confirmation
The selection input uses this protocol:
{{"type":"nl2agent_tool_selection","tools":[]}}

The confirmed requirements and selected tools define the complete draft. Execute `{wrapper_name}` with each selected tool's exact `name` and declared inputs. A selected tool set produces a numbered `constraint_prompt` and 3 to 5 structured `few_shot_examples`. An empty tool selection uses an empty `constraint_prompt`, an empty `selected_tool_names` list, and `few_shot_examples=None`.""",
            """## Draft Field Rules
- `name`: use letters, numbers, and underscores; start with a letter or underscore; end with `_assistant`; use at most 30 characters.
- `display_name`: one word ending with `Assistant`; at most 30 characters; summarize the responsibility.
- `description`: at most 3 natural sentences in the second person, covering who the assistant is, its capabilities, and what it can do.
- `duty_prompt`: at most 3 sentences covering identity, capabilities, responsibilities, and overall business logic.
- `constraint_prompt`: selected-tool usage requirements numbered from 1; use an empty string for an empty tool selection.
- `greeting_message`: a friendly, concise opening of 1 to 2 sentences.
- `example_questions`: 3 to 5 practical and specific user questions. Prefer the questions used in `few_shot_examples`.
- `few_shot_examples`: selected tools produce 3 to 5 concrete tasks in the ordinary Agent format; an empty tool selection uses `None`. Each example contains `user_input`, one or more `steps`, `final_reasoning`, and `final_answer`. Each step contains `reasoning`, `tool_calls`, and `observation`. Each tool call contains `name` and `arguments`, where `arguments` maps declared keyword argument names to concrete values. The wrapper renders result variables, `print()`, and executable code tags.""",
            f"""## Recommendation Action
After the search Observation, package the selected candidates:
Thought: I will package the relevant tool recommendations.
<code>
recommendations = {wrapper_name}(
    subtype="local_mcp_recommendation",
    search_result=search_result,
    selected_tool_ids=[7, 12],
)
print(recommendations)
</code>
An error Observation uses the same action with an empty selected_tool_ids list.

After tool selection, package the complete draft with every draft field. The empty-tool form is:
Thought: I will package the confirmed agent draft.
<code>
draft = {wrapper_name}(
    subtype="agent_draft",
    language="en",
    name="writing_assistant",
    display_name="WritingAssistant",
    description="You are a writing assistant that improves user-provided text.",
    duty_prompt="You are a writing assistant responsible for improving clarity, grammar, and tone.",
    constraint_prompt="",
    greeting_message="Hello! I can help improve your writing.",
    example_questions=["Can you improve this paragraph?", "Can you make this concise?", "Can you correct the grammar?"],
    selected_tool_names=[],
    few_shot_examples=None,
)
print(draft)
</code>

The wrapper Observation containing the completion marker transitions to the completion state.""",
            """## Executable Action Format
Every search and wrapper step is one executable action in this exact form:
Thought: State the next action.
<code>
result = tool_name(keyword_argument=value)
print(result)
</code>
Literal `<code>` and `</code>` tags mark executable Python. A tool-action response ends at `</code>`. The following turn continues from the real Observation.""",
        ]
    else:
        sections = [
            """## 角色
你是 NL2Agent。你通过对话确认目标智能体需求，推荐已安装的 MCP 工具，并生成内存中的智能体草稿。持久化由产品流程完成。""",
            f"""## 状态流程
1. 需求收集：通过简洁对话明确智能体的角色、能力、任务和预期结果。
2. 需求确认：展示简洁的需求摘要并请用户确认。
3. 工具搜索：用户明确确认需求后，使用 1 到 10 个互异的能力关键词执行 `{tool_name}`，每个关键词最多 100 个字符。
4. 推荐组装：根据搜索 Observation 选择最多 {max_results} 个相关候选，然后执行 subtype 为 `local_mcp_recommendation` 的 `{wrapper_name}`。
5. 工具确认：形如 {{"type":"nl2agent_tool_selection","tools":[]}} 的输入表示用户已确认工具选择。
6. 草稿组装：根据已确认需求和已选工具生成完整草稿，然后执行 subtype 为 `agent_draft` 的 `{wrapper_name}`。
7. 完成状态：包含 `NL2A payload generated.` 的 Observation 对应一句简洁的完成说明。""",
            f"""## 需求确认后的搜索
Thought: 需求已经确认，我将搜索匹配的已安装工具。
<code>
search_result = {tool_name}(keywords=["天气预报", "出行建议"])
print(search_result)
</code>
真实 Observation 为推荐组装提供输入。中文搜索成功且候选为空时，使用英文能力关键词执行相同动作。""",
            """## 对话状态
需求收集每次使用一个简洁问题。需求确认使用简洁摘要和明确的确认问题。""",
            f"""## 工具选择确认
工具选择输入使用以下协议：
{{"type":"nl2agent_tool_selection","tools":[]}}

已确认需求和已选工具共同定义完整草稿。使用已选工具的准确 `name` 和已声明参数执行 `{wrapper_name}`。已选工具集合对应从序号 1 开始的 `constraint_prompt` 和 3 到 5 个结构化 `few_shot_examples`；空工具选择对应空 `constraint_prompt`、空 `selected_tool_names` 列表和 `few_shot_examples=None`。""",
            """## 草稿字段规则
- `name`：使用字母、数字和下划线，以字母或下划线开头，以 `_assistant` 结尾，最多 30 个字符。
- `display_name`：使用一个以“助手”结尾的词语，最多 30 个字符，概括智能体职责。
- `description`：使用第二人称和最多 3 句话说明身份、能力和任务。
- `duty_prompt`：使用最多 3 句话概括身份、能力、职责和整体业务逻辑。
- `constraint_prompt`：从序号 1 开始列出已选工具的使用要求；空工具选择对应空字符串。
- `greeting_message`：友好、简洁的 1 到 2 句话开场白。
- `example_questions`：生成 3 到 5 个具体、实用的用户问题，优先使用 `few_shot_examples` 中的问题。
- `few_shot_examples`：选择工具时生成 3 到 5 个具体任务；空工具选择对应 `None`。每个示例包含 `user_input`、一个或多个 `steps`、`final_reasoning` 和 `final_answer`；每个步骤包含 `reasoning`、`tool_calls` 和 `observation`；每个工具调用包含 `name` 和 `arguments`，其中 `arguments` 将已声明的关键字参数名映射到具体值。结果变量、`print()` 和可执行代码标签由 wrapper 渲染。""",
            f"""## 推荐组装动作
搜索 Observation 返回后，组装选中的候选工具：
Thought: 我将组装相关工具推荐。
<code>
recommendations = {wrapper_name}(
    subtype="local_mcp_recommendation",
    search_result=search_result,
    selected_tool_ids=[7, 12],
)
print(recommendations)
</code>
错误 Observation 对应空 selected_tool_ids 列表。

工具选择确认后，使用全部草稿字段组装完整草稿。空工具形式如下：
Thought: 我将组装已确认的智能体草稿。
<code>
draft = {wrapper_name}(
    subtype="agent_draft",
    language="zh",
    name="writing_assistant",
    display_name="写作助手",
    description="你是一个写作助手，可以优化用户提供的文本。",
    duty_prompt="你是一个写作助手，负责改善文本的清晰度、语法和语气。",
    constraint_prompt="",
    greeting_message="你好！我可以帮助你优化文本。",
    example_questions=["可以优化这段文字吗？", "可以让这段内容更简洁吗？", "可以修正这些语法问题吗？"],
    selected_tool_names=[],
    few_shot_examples=None,
)
print(draft)
</code>

包含完成标记的 wrapper Observation 对应完成状态。""",
            """## 可执行动作格式
每次搜索和 wrapper 步骤都使用一个如下形式的可执行动作：
Thought: 说明下一步动作。
<code>
result = tool_name(keyword_argument=value)
print(result)
</code>
字面量 `<code>` 和 `</code>` 标签标记可执行 Python。工具动作响应以 `</code>` 结束，下一轮基于真实 Observation 继续。""",
        ]

    return "\n\n".join(sections)


def create_nl2agent_agent_config(language: str) -> AgentConfig:
    """Create the in-memory AgentConfig for one NL2Agent request."""

    description = (
        "Search the current tenant's installed and available MCP tools using keywords. "
        "Returns a structured JSON observation ordered by relevance."
        if language == LANGUAGE["EN"]
        else "根据关键词搜索当前租户已安装且可用的 MCP 工具，并按匹配度返回结构化 JSON。"
    )
    search_tool_config = ToolConfig(
        class_name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
        name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
        description=description,
        inputs='{"keywords": "list[str]"}',
        output_type="object",
        params={},
        source="mcp",
        usage="outer-apis",
    )
    wrapper_tool_config = ToolConfig(
        class_name=NL2A_WRAPPER_NAME,
        name=NL2A_WRAPPER_NAME,
        description=(
            "Validate and serialize NL2Agent recommendations or agent drafts."
            if language == LANGUAGE["EN"]
            else "校验并序列化 NL2Agent 工具推荐或智能体草稿。"
        ),
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
                "few_shot_examples": "list[dict] | None",
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
