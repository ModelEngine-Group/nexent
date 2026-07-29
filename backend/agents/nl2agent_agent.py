"""Build the ephemeral NL2Agent and its MCP tool configuration."""

import json
import keyword
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
    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    duty_prompt: str = Field(min_length=1)
    constraint_prompt: str = Field(min_length=1)
    few_shots_prompt: str | None = None
    greeting_message: str = Field(min_length=1)
    example_questions: list[str] = Field(min_length=1, max_length=6)


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


class Nl2aFewShotExample(BaseModel):
    """Structured few-shot content that contains no executable code tags."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_input: str = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    tool_calls: list[Nl2aFewShotToolCall] = Field(min_length=1)
    response_guidance: str = Field(min_length=1)


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
    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    duty_prompt: str = Field(min_length=1)
    constraint_prompt: str = Field(min_length=1)
    greeting_message: str = Field(min_length=1)
    example_questions: list[str] = Field(min_length=3, max_length=3)
    selected_tool_names: list[str] = Field(max_length=MAX_TOOL_RECOMMENDATIONS)
    few_shot_examples: list[Nl2aFewShotExample] | None = Field(
        default=None,
        min_length=3,
        max_length=5,
    )

    @model_validator(mode="after")
    def validate_few_shot_tools(self) -> "Nl2aAgentDraftInput":
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
        if not selected_names and self.few_shot_examples is not None:
            raise ValueError("few_shot_examples require selected tools")
        for example in self.few_shot_examples or []:
            unknown_names = {
                call.name for call in example.tool_calls
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

    labels = (
        ("Example", "User", "Think", "Code", "Assistant")
        if payload.language == "en"
        else ("示例", "用户", "思考", "代码", "助手")
    )
    example_label, user_label, think_label, code_label, assistant_label = labels
    rendered_examples: list[str] = []
    for example_index, example in enumerate(payload.few_shot_examples, start=1):
        code_lines: list[str] = []
        multiple_calls = len(example.tool_calls) > 1
        for call_index, call in enumerate(example.tool_calls, start=1):
            variable_name = f"result_{call_index}" if multiple_calls else "result"
            arguments = ", ".join(
                f"{name}={value!r}" for name, value in call.arguments.items()
            )
            code_lines.append(f"{variable_name} = {call.name}({arguments})")
            code_lines.append(f"print({variable_name})")

        rendered_examples.append(
            "\n".join(
                [
                    f"{example_label} {example_index}",
                    f"{user_label}: {example.user_input}",
                    f"{think_label}: {example.reasoning}",
                    f"{code_label}:",
                    "<code>",
                    *code_lines,
                    "</code>",
                    f"{assistant_label}: {example.response_guidance}",
                ]
            )
        )
    return "\n\n".join(rendered_examples)


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

Use the preceding conversation and selected tools to define the complete draft, then call `{wrapper_name}`. This path does not call the search tool. Use each selected tool's exact `name`; never invent tools or inputs. When tools are selected, provide 3 to 5 structured `few_shot_examples`. When no tools are selected, use an empty `selected_tool_names` list and `few_shot_examples` set to `None`.""",
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

For a tool selection input, call it with every required draft field. Do not put code tags in any wrapper argument. `few_shot_examples` use structured `tool_calls`, and the wrapper renders the executable examples:
Think: I will validate and wrap the complete agent draft.
Code:
<code>
wrapped = {wrapper_name}(payload={{
    "subtype": "agent_draft",
    "language": "en",
    "name": "weather_assistant",
    "display_name": "Weather Assistant",
    "description": "Checks weather and provides travel advice.",
    "duty_prompt": "Answer weather questions and provide practical advice.",
    "constraint_prompt": "Use selected weather tools and base answers on their real observations.",
    "greeting_message": "Hello! I can check forecasts and help you plan for the weather.",
    "example_questions": ["Will it rain in Shanghai tomorrow?", "What should I wear in Beijing?", "Is Hangzhou suitable for hiking today?"],
    "selected_tool_names": ["weather_forecast"],
    "few_shot_examples": [
        {{"user_input": "Will it rain in Shanghai tomorrow?", "reasoning": "Get Shanghai's forecast.", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "Shanghai"}}}}], "response_guidance": "Answer using the real observation."}},
        {{"user_input": "What should I wear in Beijing?", "reasoning": "Get Beijing's forecast first.", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "Beijing"}}}}], "response_guidance": "Give advice using the real observation."}},
        {{"user_input": "Is Hangzhou suitable for hiking today?", "reasoning": "Check Hangzhou's conditions.", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "Hangzhou"}}}}], "response_guidance": "Assess suitability using the real observation."}},
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

结合此前对话和已选工具生成完整草稿，然后调用 `{wrapper_name}`。此流程不调用搜索工具。只使用已选工具的真实 `name`，不得编造工具或参数。选择了工具时生成 3 到 5 个结构化 `few_shot_examples`；未选择工具时传入空的 `selected_tool_names`，并将 `few_shot_examples` 设为 `None`。""",
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

收到工具选择输入后，传入所有必填草稿字段。任何 wrapper 参数中都不得包含代码标签；`few_shot_examples` 使用结构化 `tool_calls`，可执行示例由 wrapper 生成：
思考：校验并包装完整的智能体草稿。
代码：
<code>
wrapped = {wrapper_name}(payload={{
    "subtype": "agent_draft",
    "language": "zh",
    "name": "weather_assistant",
    "display_name": "天气助手",
    "description": "查询天气并提供出行建议。",
    "duty_prompt": "回答天气问题并提供实用建议。",
    "constraint_prompt": "使用已选天气工具，并根据真实 Observation 回答。",
    "greeting_message": "你好！我可以查询天气预报并帮助你规划出行。",
    "example_questions": ["上海明天会下雨吗？", "北京今天适合穿什么？", "杭州今天适合徒步吗？"],
    "selected_tool_names": ["weather_forecast"],
    "few_shot_examples": [
        {{"user_input": "上海明天会下雨吗？", "reasoning": "先查询上海天气。", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "上海"}}}}], "response_guidance": "根据真实 Observation 回答。"}},
        {{"user_input": "北京今天适合穿什么？", "reasoning": "先查询北京天气。", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "北京"}}}}], "response_guidance": "根据真实 Observation 给出建议。"}},
        {{"user_input": "杭州今天适合徒步吗？", "reasoning": "先查询杭州天气。", "tool_calls": [{{"name": "weather_forecast", "arguments": {{"city": "杭州"}}}}], "response_guidance": "根据真实 Observation 判断。"}},
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
