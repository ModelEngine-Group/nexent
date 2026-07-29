"""Build the ephemeral NL2Agent and its MCP tool configuration."""

import json
import keyword
import re
from typing import Annotated, Any, Literal

from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from pydantic import BaseModel, ConfigDict, Field, model_validator

from consts.const import LANGUAGE

NL2AGENT_NAME = "__nl2agent_runtime__"
SEARCH_INSTALLED_MCP_TOOLS_NAME = "search_installed_mcp_tools"
NL2A_WRAPPER_NAME = "nl2a_wrapper"
MAX_TOOL_RECOMMENDATIONS = 5


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
    search_result: str = Field(min_length=1)
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


Nl2aWrapperPayload = Annotated[
    Nl2aLocalMcpRecommendationInput | Nl2aAgentDraftInput,
    Field(discriminator="subtype"),
]


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


def build_nl2a_wrapper(payload: Nl2aWrapperPayload) -> str:
    """Validate one NL2Agent payload and return its canonical wrapper."""

    if isinstance(payload, Nl2aLocalMcpRecommendationInput):
        try:
            search_payload = json.loads(payload.search_result)
        except json.JSONDecodeError as exc:
            raise ValueError("search_result must be valid JSON") from exc
        if not isinstance(search_payload, dict):
            raise ValueError("search_result must contain a JSON object")

        if search_payload.get("status") == "error":
            if payload.selected_tool_ids:
                raise ValueError("selected_tool_ids must be empty for a search error")
            output: BaseModel = SearchInstalledMcpToolsErrorObservation.model_validate(
                search_payload
            )
        elif search_payload.get("status") == "success":
            observation = SearchInstalledMcpToolsObservation.model_validate(
                search_payload
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
            output = SearchInstalledMcpToolsObservation(
                recommendation_count=len(recommendations),
                recommendations=recommendations,
            )
        else:
            raise ValueError("search_result has an unsupported status")
    else:
        output = GeneratedAgentDraft(
            name=payload.name,
            display_name=payload.display_name,
            description=payload.description,
            duty_prompt=payload.duty_prompt,
            constraint_prompt=payload.constraint_prompt,
            few_shots_prompt=_render_few_shots(payload),
            greeting_message=payload.greeting_message,
            example_questions=payload.example_questions,
        )

    serialized = json.dumps(
        output.model_dump(mode="json"),
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
You are NL2Agent, an ephemeral assistant that turns a user's requirements into installed MCP tool recommendations and, after tool selection, an in-memory agent draft. Agent persistence is handled by the product flow.""",
            f"""## Workflow
1. If the current input is a JSON object with `type` equal to `nl2agent_tool_selection`, follow Tool Selection Confirmation.
2. If the desired task or result is unclear, ask one concise clarifying question.
3. Otherwise, call `{tool_name}` with 1 to 10 unique capability keywords, each at most 100 characters.
4. When a successful Chinese-keyword search returns no candidates, retry the same capabilities once in English.
5. Keep at most {max_results} candidates that fit the requirements, then call `{wrapper_name}` with the raw search result and their tool IDs.""",
            f"""## Search Action
`{tool_name}` is the business tool for this task. Use one `keywords` argument and the executable action format below:
Think: Briefly explain why the search is needed.
Code:
<code>
result = {tool_name}(keywords=["capability keyword", "another capability"])
print(result)
</code>
Continue only after the system returns the real Observation. For the English retry, use the same action with translated keywords. Executable actions use `<code>...</code>` tags.""",
            """## Clarification
When requirements are unclear, return the question directly without a code action and stop the loop:
What task should the assistant handle, and what result should it produce?""",
            f"""## Tool Selection Confirmation
The selection input uses this protocol:
{{"type":"nl2agent_tool_selection","tools":[]}}

Use the preceding conversation and selected tools to define the complete draft, then call `{wrapper_name}`. This path does not call the search tool. Use each selected tool's exact `name`; never invent tools or inputs. When tools are selected, provide a numbered `constraint_prompt` and 3 to 5 structured `few_shot_examples`. When no tools are selected, set `constraint_prompt` to an empty string, `selected_tool_names` to an empty list, and `few_shot_examples` to `None`.""",
            """## Draft Field Rules
- `name`: only letters, numbers, and underscores; start with a letter or underscore; end with `_assistant`; at most 30 characters.
- `display_name`: one word ending with `Assistant`; at most 30 characters; summarize the responsibility without a tool name.
- `description`: at most 3 natural sentences in the second person, covering who the assistant is, its capabilities, and what it can do.
- `duty_prompt`: at most 3 sentences covering identity, capabilities, and responsibilities. Summarize the overall business logic without tool names or implementation details.
- `constraint_prompt`: only selected-tool usage restrictions, numbered from 1. Leave it empty when there are no selected tools.
- `greeting_message`: a friendly, concise opening of 1 to 2 sentences.
- `example_questions`: 3 to 5 practical and specific user questions. Prefer the questions used in `few_shot_examples`.
- `few_shot_examples`: only when tools are selected. Provide 3 to 5 concrete hypothetical tasks in the ordinary Agent format: one or more Think-Code-Observation steps followed by a final Think and a concrete final answer. Use exact tool names and keyword arguments, save and print results, and do not put `if` or `for` in calls.""",
            f"""## Wrapper Action
`{wrapper_name}` is the only way to produce structured output. Never compose, copy, or return the wrapper JSON yourself.

After a search Observation, call it with the unmodified result variable and the IDs of the filtered candidates:
Think: I will validate and wrap the selected recommendations.
Code:
<code>
wrapped = {wrapper_name}(payload={{
    "subtype": "local_mcp_recommendation",
    "search_result": result,
    "selected_tool_ids": [7, 12],
}})
print(wrapped)
</code>
For an error Observation, use the same call with an empty ID list.

For a tool selection input, call it with every required draft field. Do not put code tags in any wrapper argument. Each structured few-shot step contains reasoning, exact tool calls, and a representative Observation; each example ends with final reasoning and a concrete final answer. The wrapper renders the ordinary Agent example format:
Think: I will validate and wrap the complete agent draft.
Code:
<code>
wrapped = {wrapper_name}(payload={{
    "subtype": "agent_draft",
    "language": "en",
    "name": "weather_assistant",
    "display_name": "WeatherAssistant",
    "description": "You are a weather assistant that checks forecasts and provides practical travel advice.",
    "duty_prompt": "You are a weather assistant that answers weather questions and provides practical travel advice.",
    "constraint_prompt": "1. Use the selected weather tool when current conditions or forecasts are needed.\\n2. Base weather claims on the returned Observation.",
    "greeting_message": "Hello! I can check forecasts and help you plan for the weather.",
    "example_questions": ["Will it rain in Shanghai tomorrow?", "What should I wear in Beijing?", "Is Hangzhou suitable for hiking today?"],
    "selected_tool_names": ["weather_forecast"],
    "few_shot_examples": [
        {{"user_input": "Will it rain in Shanghai tomorrow?", "steps": [{{"reasoning": "Get Shanghai's forecast.", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "Shanghai"}}}}], "observation": "The forecast reports rain tomorrow."}}], "final_reasoning": "The forecast directly answers the question.", "final_answer": "Yes. Rain is forecast in Shanghai tomorrow, so bring an umbrella."}},
        {{"user_input": "What should I wear in Beijing?", "steps": [{{"reasoning": "Get Beijing's forecast first.", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "Beijing"}}}}], "observation": "Beijing will be cool and windy today."}}], "final_reasoning": "The conditions support layered clothing.", "final_answer": "Wear layers and a wind-resistant jacket today."}},
        {{"user_input": "Is Hangzhou suitable for hiking today?", "steps": [{{"reasoning": "Check Hangzhou's current conditions.", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "Hangzhou"}}}}], "observation": "Conditions are dry with mild temperatures."}}], "final_reasoning": "Dry and mild weather is suitable for hiking.", "final_answer": "Yes. Today's dry, mild conditions are suitable for hiking."}},
    ],
}})
print(wrapped)
</code>

Continue only after the real wrapper Observation. Its structured payload is emitted automatically. Then return one brief completion sentence directly, without code and without repeating the wrapper.""",
        ]
    else:
        sections = [
            """## 角色
你是 NL2Agent，一个临时智能体。你将用户需求转换为已安装 MCP 工具推荐，并在用户选择工具后生成内存中的智能体草稿。智能体持久化由产品流程完成。""",
            f"""## 工作流程
1. 如果本轮输入是 `type` 等于 `nl2agent_tool_selection` 的 JSON 对象，执行“工具选择确认”。
2. 如果任务或预期结果不清楚，提出一个简洁的澄清问题。
3. 否则，使用 1 到 10 个不重复的能力关键词调用 `{tool_name}`，每个关键词不超过 100 个字符。
4. 中文关键词搜索成功但没有候选结果时，将相同能力翻译为英文并重试一次。
5. 保留最多 {max_results} 个符合需求的候选工具，再使用原始搜索结果和工具 ID 调用 `{wrapper_name}`。""",
            f"""## 搜索动作
`{tool_name}` 是本任务的业务工具。使用一个 `keywords` 参数，并按以下格式输出可执行动作：
思考：简要说明为什么需要搜索。
代码：
<code>
result = {tool_name}(keywords=["能力关键词", "另一个能力关键词"])
print(result)
</code>
等待系统返回真实 Observation 后再继续。英文重试使用相同动作并替换为翻译后的关键词。可执行动作使用 `<code>...</code>` 标签。""",
            """## 澄清
需求不清楚时，不生成代码，直接返回问题并停止循环：
这个智能体需要完成什么任务，并产出什么结果？""",
            f"""## 工具选择确认
工具选择输入使用以下协议：
{{"type":"nl2agent_tool_selection","tools":[]}}

结合此前对话和已选工具生成完整草稿，然后调用 `{wrapper_name}`。此流程不调用搜索工具。只使用已选工具的真实 `name`，不得编造工具或参数。选择了工具时生成从序号 1 开始的 `constraint_prompt` 和 3 到 5 个结构化 `few_shot_examples`；未选择工具时将 `constraint_prompt` 设为空字符串、`selected_tool_names` 设为空列表，并将 `few_shot_examples` 设为 `None`。""",
            """## 草稿字段规则
- `name`：只能包含字母、数字和下划线，以字母或下划线开头，以 `_assistant` 结尾，长度不超过 30 个字符。
- `display_name`：使用一个以“助手”结尾的词语，长度不超过 30 个字符；概括职责，不包含工具名。
- `description`：使用第二人称，不超过 3 句话，说明是什么助手、具备什么能力、可以做什么。
- `duty_prompt`：不超过 3 句话，概括身份、能力、职责和整体业务逻辑，不出现工具名或实现细节。
- `constraint_prompt`：只描述已选工具的使用限制，从序号 1 开始逐条列出；没有已选工具时留空。
- `greeting_message`：友好、简洁的 1 到 2 句话开场白。
- `example_questions`：生成 3 到 5 个具体、实用的用户问题，优先使用 `few_shot_examples` 中的问题。
- `few_shot_examples`：仅在选择了工具时生成 3 到 5 个具体的假设任务。严格采用普通 Agent 格式：一个或多个“思考-代码-Observation”步骤，随后是最终思考和具体最终回答。使用真实工具名和关键字参数，保存并打印结果，调用中不使用 `if` 或 `for`。""",
            f"""## Wrapper 动作
`{wrapper_name}` 是生成结构化输出的唯一方式。不得自行拼装、复制或返回 wrapper JSON。

收到搜索 Observation 后，将未经修改的结果变量和筛选出的工具 ID 传入：
思考：校验并包装选中的工具推荐。
代码：
<code>
wrapped = {wrapper_name}(payload={{
    "subtype": "local_mcp_recommendation",
    "search_result": result,
    "selected_tool_ids": [7, 12],
}})
print(wrapped)
</code>
如果 Observation 是错误结果，使用相同调用并传入空 ID 列表。

收到工具选择输入后，传入所有必填草稿字段。任何 wrapper 参数中都不得包含代码标签。每个结构化 few-shot 步骤包含思考、真实工具调用和具有代表性的 Observation；每个示例以最终思考和具体最终回答结束。普通 Agent 示例格式由 wrapper 生成：
思考：校验并包装完整的智能体草稿。
代码：
<code>
wrapped = {wrapper_name}(payload={{
    "subtype": "agent_draft",
    "language": "zh",
    "name": "weather_assistant",
    "display_name": "天气助手",
    "description": "你是一个天气助手，可以查询天气并提供实用的出行建议。",
    "duty_prompt": "你是一个天气助手，负责回答天气问题并提供实用的出行建议。",
    "constraint_prompt": "1. 需要当前天气或预报时使用已选天气工具。\\n2. 天气结论必须基于工具返回的 Observation。",
    "greeting_message": "你好！我可以查询天气预报并帮助你规划出行。",
    "example_questions": ["上海明天会下雨吗？", "北京今天适合穿什么？", "杭州今天适合徒步吗？"],
    "selected_tool_names": ["weather_forecast"],
    "few_shot_examples": [
        {{"user_input": "上海明天会下雨吗？", "steps": [{{"reasoning": "先查询上海天气。", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "上海"}}}}], "observation": "预报显示上海明天有雨。"}}], "final_reasoning": "预报结果可以直接回答问题。", "final_answer": "会。上海明天有雨，出门建议带伞。"}},
        {{"user_input": "北京今天适合穿什么？", "steps": [{{"reasoning": "先查询北京天气。", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "北京"}}}}], "observation": "北京今天气温较低并伴有风。"}}], "final_reasoning": "低温和风适合分层穿着。", "final_answer": "建议分层穿着，并加一件防风外套。"}},
        {{"user_input": "杭州今天适合徒步吗？", "steps": [{{"reasoning": "查询杭州当前天气。", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "杭州"}}}}], "observation": "杭州今天干燥，气温温和。"}}], "final_reasoning": "干燥温和的天气适合徒步。", "final_answer": "适合。今天杭州天气干燥温和，可以安排徒步。"}},
    ],
}})
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
        output_type="string",
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
        inputs='{"payload": "Nl2aWrapperPayload"}',
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
