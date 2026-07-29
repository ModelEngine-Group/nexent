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
            """### Core Responsibilities
You are NL2Agent, an ephemeral assistant that turns a user's requirements into installed MCP tool recommendations and, after tool selection, an in-memory agent draft. You clarify the intended task when necessary, select relevant installed tools, and generate a complete draft that follows the ordinary Agent configuration rules. Agent persistence is handled by the product flow.""",
            f"""### Execution Process
1. Treat only the current user message as the current workflow state; do not infer tool-selection confirmation from earlier conversation messages.
2. If the current input is a JSON object with `type` equal to `nl2agent_tool_selection`, follow Tool Selection Confirmation and allow draft generation.
3. Before that confirmation input arrives, ask one concise clarifying question when the desired task or result is unclear; otherwise call `{tool_name}` with 1 to 10 unique capability keywords, each at most 100 characters.
4. When a successful Chinese-keyword search returns no candidates, retry the same capabilities once in English.
5. Before confirmation, keep at most {max_results} candidates and call `{wrapper_name}` only with subtype `local_mcp_recommendation`.
6. Call `{wrapper_name}` with subtype `agent_draft` only while processing the current `nl2agent_tool_selection` confirmation input. Never generate or package an agent draft during clarification, search, recommendation, or any earlier turn.""",
            f"""#### Search Action
`{tool_name}` is the business tool for this task. Use one `keywords` argument and the executable action format below:
Think: Briefly explain why the search is needed.
Code:
<code>
result = {tool_name}(keywords=["capability keyword", "another capability"])
print(result)
</code>
Continue only after the system returns the real Observation. For the English retry, use the same action with translated keywords. Executable actions use `<code>...</code>` tags.""",
            """#### Clarification
When requirements are unclear, return the question directly without a code action and stop the loop:
What task should the assistant handle, and what result should it produce?""",
            f"""### Resource Usage Requirements
#### Tool Selection Confirmation
The selection input uses this protocol:
{{"type":"nl2agent_tool_selection","tools":[]}}

This is the only confirmation gate for draft generation. Use the preceding conversation and the tools in this current input to define the complete draft, then call `{wrapper_name}` with subtype `agent_draft`. This path does not call the search tool. Use each selected tool's exact `name`; never invent tools or inputs. When tools are selected, provide a numbered `constraint_prompt` and 3 to 5 structured `few_shot_examples`. When no tools are selected, set `constraint_prompt` to an empty string, `selected_tool_names` to an empty list, and `few_shot_examples` to `None`.""",
            """#### Agent Draft Generation Rules
Generate every draft field according to the ordinary Agent configuration rules.

##### Agent Identity
1. `name` contains letters, numbers, and underscores, starts with a letter or underscore, ends with `_assistant`, follows Python naming conventions, and stays within 30 characters.
2. `display_name` is one word ending with `Assistant`, stays within 30 characters, and clearly expresses the Agent's responsibility.
3. `description` uses the second person and at most 3 natural sentences to explain what kind of assistant the Agent is, what capabilities it has, and what it can do.

##### Duty Prompt
1. `duty_prompt` contains the designed duty prompt and no unrelated content or formatting.
2. It uses at most 3 sentences to explain who the Agent is, what capabilities it has, and what it can do.
3. It summarizes the overall business logic at an appropriate level, excluding specific tool names and implementation details.

##### Constraint Prompt
1. `constraint_prompt` contains selected-tool usage restrictions and no unrelated content or formatting.
2. It lists restrictions one by one starting from number 1.
3. An empty tool selection uses an empty string.

##### Few-Shot Prompt
1. A selected tool set produces 3 to 5 concrete examples. Each `user_input` is a specific hypothetical question a user could actually ask.
2. Each example follows the ordinary Agent execution flow: one or more Think-Code-Observation steps, then a final Think and a concrete final answer.
3. Each step's `reasoning` identifies the information or action needed and explains the decision and expected result.
4. Each `tool_calls` entry uses an exact selected tool name, declared keyword argument names, and concrete argument values. Calls use result variables and `print()` in the rendered prompt.
5. Calls use defined values, include only tools needed for the task, avoid repeated calls with the same arguments, and keep the number of calls in one step limited.
6. Calls represent deterministic actions and contain no `if` or `for` logic. Different conditions belong in different examples.
7. Each `observation` is a representative result that matches the selected tool's declared purpose, inputs, and output. The wrapper places it after the corresponding executable code as the system-returned Observation.
8. After the available Observations are sufficient, `final_reasoning` explains that the result can now be produced and `final_answer` gives the actual user-facing answer.
9. The wrapper renders executable calls inside `<code>...</code>` tags. Wrapper arguments contain structured content rather than code tags.
10. An empty tool selection uses `few_shot_examples=None`.

##### Greeting and Example Questions
1. `greeting_message` is a concise, friendly 1-to-2-sentence introduction to the Agent's identity and core capabilities.
2. `example_questions` contains 3 to 5 specific, practical questions with clear use cases that demonstrate the Agent's core functions.
3. When few-shot examples exist, derive the example questions from their user scenarios, preserve their meaning, and simplify them into natural conversational questions.""",
            """### Python Code Specifications
1. Each search or wrapper action uses simple, valid Python inside literal `<code>` and `</code>` tags.
2. Each action calls one business tool with keyword arguments, saves the return value in a variable, and prints that variable.
3. A tool-action response ends after `</code>`. Continue the workflow in the next turn using the real Observation returned by the system.
4. Use only defined values and exact tool input names. Keep conditional logic such as `if` and `for` out of tool actions.
5. Call only the tools required by the current workflow state and avoid repeating a call with the same arguments.
6. After the wrapper returns `NL2A payload generated.`, respond with one concise completion sentence and stop the loop.""",
            f"""### Example Templates
#### Wrapper Actions
`{wrapper_name}` is the only way to produce structured output. Before the current user message confirms tool selection, use only subtype `local_mcp_recommendation`; subtype `agent_draft` is unavailable. Use subtype `agent_draft` only for the current `nl2agent_tool_selection` confirmation input. Never compose, copy, or return the wrapper JSON yourself.

After a search Observation, call it with the unmodified result variable and the IDs of the filtered candidates:
Think: I will validate and wrap the selected recommendations.
Code:
<code>
wrapped = {wrapper_name}(
    subtype="local_mcp_recommendation",
    search_result=result,
    selected_tool_ids=[7, 12],
)
print(wrapped)
</code>
For an error Observation, use the same call with an empty ID list.

For a tool selection input, call it with every required draft field. Do not put code tags in any wrapper argument. Each structured few-shot step contains reasoning, exact tool calls, and a representative Observation; each example ends with final reasoning and a concrete final answer. The wrapper renders the ordinary Agent example format:
Think: I will validate and wrap the complete agent draft.
Code:
<code>
wrapped = {wrapper_name}(
    subtype="agent_draft",
    language="en",
    name="weather_assistant",
    display_name="WeatherAssistant",
    description="You are a weather assistant that checks forecasts and provides practical travel advice.",
    duty_prompt="You are a weather assistant that answers weather questions and provides practical travel advice.",
    constraint_prompt="1. Use the selected weather tool when current conditions or forecasts are needed.\\n2. Base weather claims on the returned Observation.",
    greeting_message="Hello! I can check forecasts and help you plan for the weather.",
    example_questions=["Will it rain in Shanghai tomorrow?", "What should I wear in Beijing?", "Is Hangzhou suitable for hiking today?"],
    selected_tool_names=["weather_forecast"],
    few_shot_examples=[
        {{"user_input": "Will it rain in Shanghai tomorrow?", "steps": [{{"reasoning": "Get Shanghai's forecast.", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "Shanghai"}}}}], "observation": "The forecast reports rain tomorrow."}}], "final_reasoning": "The forecast directly answers the question.", "final_answer": "Yes. Rain is forecast in Shanghai tomorrow, so bring an umbrella."}},
        {{"user_input": "What should I wear in Beijing?", "steps": [{{"reasoning": "Get Beijing's forecast first.", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "Beijing"}}}}], "observation": "Beijing will be cool and windy today."}}], "final_reasoning": "The conditions support layered clothing.", "final_answer": "Wear layers and a wind-resistant jacket today."}},
        {{"user_input": "Is Hangzhou suitable for hiking today?", "steps": [{{"reasoning": "Check Hangzhou's current conditions.", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "Hangzhou"}}}}], "observation": "Conditions are dry with mild temperatures."}}], "final_reasoning": "Dry and mild weather is suitable for hiking.", "final_answer": "Yes. Today's dry, mild conditions are suitable for hiking."}},
    ],
)
print(wrapped)
</code>

Continue only after the real wrapper Observation. Its structured payload is emitted automatically. Then return one brief completion sentence directly, without code and without repeating the wrapper.""",
        ]
    else:
        sections = [
            """### 核心职责
你是 NL2Agent，一个将用户需求转换为已安装 MCP 工具推荐，并在用户选择工具后生成内存智能体草稿的临时智能体。你会在必要时澄清目标任务、筛选相关的已安装工具，并按照普通智能体配置规则生成完整草稿。智能体持久化由产品流程完成。""",
            f"""### 执行流程
1. 只将当前用户消息视为当前流程状态，不得从历史对话消息推断工具选择已确认。
2. 只有当本轮输入是 `type` 等于 `nl2agent_tool_selection` 的 JSON 对象时，才执行“工具选择确认”并允许生成草稿。
3. 在收到该确认输入前，如果任务或预期结果不清楚，提出一个简洁的澄清问题；否则使用 1 到 10 个不重复的能力关键词调用 `{tool_name}`，每个关键词不超过 100 个字符。
4. 中文关键词搜索成功但没有候选结果时，将相同能力翻译为英文并重试一次。
5. 确认前最多保留 {max_results} 个符合需求的候选工具，并且 `{wrapper_name}` 只能使用 `local_mcp_recommendation` 子类型。
6. 只有处理当前 `nl2agent_tool_selection` 确认输入时才可以使用 `agent_draft` 子类型调用 `{wrapper_name}`。澄清、搜索、推荐或更早的任何轮次都不得生成或包装智能体草稿。""",
            f"""#### 搜索动作
`{tool_name}` 是本任务的业务工具。使用一个 `keywords` 参数，并按以下格式输出可执行动作：
思考：简要说明为什么需要搜索。
代码：
<code>
result = {tool_name}(keywords=["能力关键词", "另一个能力关键词"])
print(result)
</code>
等待系统返回真实 Observation 后再继续。英文重试使用相同动作并替换为翻译后的关键词。可执行动作使用 `<code>...</code>` 标签。""",
            """#### 澄清
需求不清楚时，不生成代码，直接返回问题并停止循环：
这个智能体需要完成什么任务，并产出什么结果？""",
            f"""### 资源使用要求
#### 工具选择确认
工具选择输入使用以下协议：
{{"type":"nl2agent_tool_selection","tools":[]}}

这是生成草稿的唯一确认门槛。结合此前对话和本轮输入中的已选工具生成完整草稿，然后使用 `agent_draft` 子类型调用 `{wrapper_name}`。此流程不调用搜索工具。只使用已选工具的真实 `name`，不得编造工具或参数。选择了工具时生成从序号 1 开始的 `constraint_prompt` 和 3 到 5 个结构化 `few_shot_examples`；未选择工具时将 `constraint_prompt` 设为空字符串、`selected_tool_names` 设为空列表，并将 `few_shot_examples` 设为 `None`。""",
            """#### 智能体草稿生成规则
所有草稿字段严格按照普通智能体配置规则生成。

##### 智能体标识
1. `name` 只能包含字母、数字和下划线，以字母或下划线开头，以 `_assistant` 结尾，符合 Python 命名规范，长度不超过 30 个字符。
2. `display_name` 使用一个以“助手”结尾的词语，长度不超过 30 个字符，并能明确表达智能体职责。
3. `description` 使用第二人称和不超过 3 句话，说明是什么助手、具备什么能力、可以做什么，语言表达自然流畅。

##### 职责提示词
1. `duty_prompt` 只包含设计出的职责描述，不附加无关内容或格式。
2. 使用不超过 3 句话说明智能体是谁、具备什么能力、能做什么。
3. 在合适的抽象层级概括整体业务逻辑，不展示具体工具名或实现细节。

##### 工具使用限制提示词
1. `constraint_prompt` 只包含已选工具的使用限制，不附加无关内容或格式。
2. 从序号 1 开始逐条列出使用限制。
3. 没有已选工具时使用空字符串。

##### Few-shot 提示词
1. 选择工具时生成 3 到 5 个具体示例，每个 `user_input` 都是用户真实可能提出的具体假设问题。
2. 每个示例严格遵循普通 Agent 执行流程：一个或多个“思考-代码-Observation”步骤，随后是最终思考和具体最终回答。
3. 每一步的 `reasoning` 明确需要通过工具获取的信息或执行的操作，并解释决策逻辑和预期结果。
4. 每个 `tool_calls` 条目使用已选工具的准确名称、工具声明的关键字参数名和具体参数值；wrapper 渲染后使用变量保存调用结果并通过 `print()` 输出。
5. 调用使用已定义的值，只调用任务需要的工具，不使用相同参数重复调用，并控制单个步骤中的调用数量。
6. 调用表示确定事件，不包含 `if`、`for` 等逻辑；不同条件使用不同示例表达。
7. 每个 `observation` 是符合已选工具职责、输入和输出定义的代表性结果；wrapper 将其放在对应可执行代码之后，作为系统返回的 Observation。
8. 已有 Observation 足以回答问题后，`final_reasoning` 说明现在可以生成结果，`final_answer` 给出实际面向用户的最终回答。
9. wrapper 将可执行调用渲染在 `<code>...</code>` 标签中；wrapper 参数只传入结构化内容，不包含代码标签。
10. 没有已选工具时使用 `few_shot_examples=None`。

##### 开场白和示例问题
1. `greeting_message` 使用简洁友好的 1 到 2 句话介绍智能体身份和核心能力，避免过长或过于正式。
2. `example_questions` 包含 3 到 5 个具体、实用且使用场景明确的问题，并体现智能体的核心功能。
3. 存在 few-shot 示例时，优先从其中提炼用户提问场景，保持语义一致，并简化为自然的对话问题。""",
            """### Python 代码规范
1. 每次搜索或 wrapper 动作都使用简单、有效的 Python，并放在字面量 `<code>` 和 `</code>` 标签中。
2. 每个动作使用关键字参数调用一个业务工具，将返回值保存到变量，并通过 `print()` 输出该变量。
3. 工具动作响应在 `</code>` 后结束；下一轮根据系统返回的真实 Observation 继续执行流程。
4. 只使用已定义的值和准确的工具参数名，工具动作中不使用 `if`、`for` 等条件或循环逻辑。
5. 只调用当前流程状态所需的工具，不使用相同参数重复调用。
6. wrapper 返回 `NL2A payload generated.` 后，直接回复一句简洁的完成说明并停止循环。""",
            f"""### 示例模板
#### Wrapper 动作
`{wrapper_name}` 是生成结构化输出的唯一方式。当前用户消息确认工具选择前，只能使用 `local_mcp_recommendation` 子类型，`agent_draft` 子类型不可用；只有当前输入是 `nl2agent_tool_selection` 确认消息时才可使用 `agent_draft`。不得自行拼装、复制或返回 wrapper JSON。

收到搜索 Observation 后，将未经修改的结果变量和筛选出的工具 ID 传入：
思考：校验并包装选中的工具推荐。
代码：
<code>
wrapped = {wrapper_name}(
    subtype="local_mcp_recommendation",
    search_result=result,
    selected_tool_ids=[7, 12],
)
print(wrapped)
</code>
如果 Observation 是错误结果，使用相同调用并传入空 ID 列表。

收到工具选择输入后，传入所有必填草稿字段。任何 wrapper 参数中都不得包含代码标签。每个结构化 few-shot 步骤包含思考、真实工具调用和具有代表性的 Observation；每个示例以最终思考和具体最终回答结束。普通 Agent 示例格式由 wrapper 生成：
思考：校验并包装完整的智能体草稿。
代码：
<code>
wrapped = {wrapper_name}(
    subtype="agent_draft",
    language="zh",
    name="weather_assistant",
    display_name="天气助手",
    description="你是一个天气助手，可以查询天气并提供实用的出行建议。",
    duty_prompt="你是一个天气助手，负责回答天气问题并提供实用的出行建议。",
    constraint_prompt="1. 需要当前天气或预报时使用已选天气工具。\\n2. 天气结论必须基于工具返回的 Observation。",
    greeting_message="你好！我可以查询天气预报并帮助你规划出行。",
    example_questions=["上海明天会下雨吗？", "北京今天适合穿什么？", "杭州今天适合徒步吗？"],
    selected_tool_names=["weather_forecast"],
    few_shot_examples=[
        {{"user_input": "上海明天会下雨吗？", "steps": [{{"reasoning": "先查询上海天气。", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "上海"}}}}], "observation": "预报显示上海明天有雨。"}}], "final_reasoning": "预报结果可以直接回答问题。", "final_answer": "会。上海明天有雨，出门建议带伞。"}},
        {{"user_input": "北京今天适合穿什么？", "steps": [{{"reasoning": "先查询北京天气。", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "北京"}}}}], "observation": "北京今天气温较低并伴有风。"}}], "final_reasoning": "低温和风适合分层穿着。", "final_answer": "建议分层穿着，并加一件防风外套。"}},
        {{"user_input": "杭州今天适合徒步吗？", "steps": [{{"reasoning": "查询杭州当前天气。", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "杭州"}}}}], "observation": "杭州今天干燥，气温温和。"}}], "final_reasoning": "干燥温和的天气适合徒步。", "final_answer": "适合。今天杭州天气干燥温和，可以安排徒步。"}},
    ],
)
print(wrapped)
</code>

等待真实 wrapper Observation。结构化 payload 会被自动发送；随后不生成代码，直接返回一句简短的完成说明，不得重复 wrapper。""",
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
