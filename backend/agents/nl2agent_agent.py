"""Build the ephemeral NL2Agent and its MCP tool configuration."""

from typing import Any, Literal

from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from pydantic import BaseModel, ConfigDict, Field

from consts.const import LANGUAGE

NL2AGENT_NAME = "__nl2agent_runtime__"
SEARCH_INSTALLED_MCP_TOOLS_NAME = "search_installed_mcp_tools"
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


def build_nl2agent_system_prompt(
    language: str,
    tool_name: str = SEARCH_INSTALLED_MCP_TOOLS_NAME,
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
5. Keep the candidates that fit the requirements and return at most {max_results} recommendations.""",
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
            """## Tool Selection Confirmation
The selection input uses this protocol:
{"type":"nl2agent_tool_selection","tools":[]}

Use the preceding conversation and selected tools to define the agent's responsibilities and constraints, then return the draft below. This path does not call the search tool.""",
            """## Output Contract
After thinking, return the final response directly without a code action and stop the loop.

For a selection input, return exactly one draft object inside the wrapper:
<nl2a>
{"subtype":"agent_draft","name":"weather_assistant","display_name":"Weather Assistant","description":"Checks weather and provides travel advice","duty_prompt":"...","constraint_prompt":"...","few_shots_prompt":null,"greeting_message":"Hello! I'm your weather assistant. I can check forecasts and help you plan around the conditions.","example_questions":["Will it rain in Shanghai tomorrow?","What should I wear in Beijing this weekend?","Is the weather suitable for hiking in Hangzhou today?"]}
</nl2a>
The agent draft is ready.

The draft object uses exactly the fields shown. Write a concise greeting that introduces the agent's purpose and exactly three distinct example questions grounded in the user's requirements. Selected tools inform the prompts but are not fields in this payload.

After a search, return the filtered observation inside the wrapper:
<nl2a>
{"subtype":"local_mcp_recommendation","status":"success","recommendation_count":0,"recommendations":[]}
</nl2a>
The installed tool search is complete.

Use only objects from the tool observation. Preserve every field in each selected object, including `inputs` as a JSON object, and update `recommendation_count`. For an error observation, return the complete error object. Keep the sentence after the wrapper brief and consistent with its JSON.""",
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
5. 保留符合需求的候选工具，最多返回 {max_results} 个推荐。""",
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
            """## 工具选择确认
工具选择输入使用以下协议：
{"type":"nl2agent_tool_selection","tools":[]}

结合此前对话和已选工具定义智能体职责与约束，然后返回下方草稿。此流程不调用搜索工具。""",
            """## 输出契约
思考结束后，不生成代码，直接返回最终回答并停止循环。

收到工具选择输入时，在 wrapper 中返回且只返回一个草稿对象：
<nl2a>
{"subtype":"agent_draft","name":"weather_assistant","display_name":"天气助手","description":"查询天气并提供出行建议","duty_prompt":"...","constraint_prompt":"...","few_shots_prompt":null,"greeting_message":"你好！我是天气助手，可以查询天气预报并根据天气情况提供出行建议。","example_questions":["上海明天会下雨吗？","北京这个周末适合穿什么？","杭州今天的天气适合徒步吗？"]}
</nl2a>
智能体草稿已经生成。

草稿对象只使用示例中的字段。生成一条简洁的问候语，说明智能体用途；再根据用户需求生成三个不同且具体的示例问题。已选工具用于生成提示词，但不是该 payload 的字段。

搜索完成后，将筛选后的 Observation 放入 wrapper：
<nl2a>
{"subtype":"local_mcp_recommendation","status":"success","recommendation_count":0,"recommendations":[]}
</nl2a>
已完成已安装工具搜索。

推荐对象只能来自工具 Observation。保留每个选中对象的全部字段，`inputs` 保持为 JSON 对象，并同步更新 `recommendation_count`。错误时返回完整的错误对象。wrapper 后的说明保持简短，并与其中的 JSON 一致。""",
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
    tool_config = ToolConfig(
        class_name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
        name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
        description=description,
        inputs='{"keywords": "list[str]"}',
        output_type="string",
        params={},
        source="mcp",
        usage="outer-apis",
    )

    return AgentConfig(
        name=NL2AGENT_NAME,
        description="Ephemeral natural-language agent builder",
        prompt_templates=None,
        tools=[tool_config],
        max_steps=5,
        model_name="main_model",
        provide_run_summary=False,
        instructions=build_nl2agent_system_prompt(language),
        enable_planning=False,
    )
