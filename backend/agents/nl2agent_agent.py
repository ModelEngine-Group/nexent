"""Build the ephemeral NL2Agent and its MCP tool configuration."""

from typing import Literal

from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from pydantic import BaseModel, ConfigDict, Field

from consts.const import LANGUAGE

NL2AGENT_NAME = "__nl2agent_runtime__"
SEARCH_INSTALLED_MCP_TOOLS_NAME = "search_installed_mcp_tools"
MAX_TOOL_RECOMMENDATIONS = 5


class GeneratedAgentDraft(BaseModel):
    """Complete in-memory agent draft for the agent creation flow."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    duty_prompt: str = Field(min_length=1)
    constraint_prompt: str = Field(min_length=1)
    few_shots_prompt: str | None = None


class InstalledMcpToolRecommendation(BaseModel):
    """Safe display metadata for one installed MCP tool recommendation."""

    tool_id: int
    name: str
    origin_name: str | None = None
    description: str
    source: Literal["mcp"] = "mcp"
    usage: str
    labels: list[str]
    score: float


class SearchInstalledMcpToolsObservation(BaseModel):
    """Successful structured observation returned to the agent."""

    status: Literal["success"] = "success"
    recommendation_count: int
    recommendations: list[InstalledMcpToolRecommendation]


class SearchInstalledMcpToolsErrorObservation(BaseModel):
    """Safe structured error returned to the agent."""

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
You are NL2Agent, an ephemeral assistant that clarifies a user's desired agent and searches the current tenant's installed MCP tool catalog. This run does not create or persist an agent.""",
            f"""## Workflow
1. If the user's goal is not clear enough to identify required capabilities, ask a concise clarifying question and do not call a tool.
2. Once the goal is clear, select 1 to 10 concise keywords that describe the required tool capabilities and call `{tool_name}` with those keywords.
3. Review the returned candidates against the user's requirements. Keep only suitable recommendations and order them consistently with the visible recommendation text. The tool returns at most {max_results} candidates.
4. Return the filtered recommendations in the structured final response format below.""",
            """## Keyword Schema
Pass exactly one `keywords` array with this shape:
```json
{"keywords": ["capability keyword", "another capability"]}
```
Use 1 to 10 unique, non-empty strings. Each string must be at most 100 characters. Do not add fields.""",
            f"""## Tool Call Format
When calling `{tool_name}`, output the executable action in this format:
Thought: Briefly explain why the search is needed.
Code:
<code>
result = {tool_name}(keywords=["capability keyword", "another capability"])
print(result)
</code>
Executable code must use the `<code>...</code>` tags. Never use a Markdown fenced code block with a `python` language marker for an executable action. The JSON block above documents the keyword schema only; it is not an executable action format.""",
            f"""## Few-shot Examples
### Unclear Request
User: Build an assistant for my team.
Assistant: What task should the assistant handle, and what result should it produce?

### Clear Request
User: Build an assistant that checks the weather forecast for a city and summarizes whether to carry an umbrella.
Assistant:
Thought: The request is clear enough to search for installed weather and forecast capabilities.
Code:
<code>
result = {tool_name}(keywords=["weather forecast", "city weather", "rain probability"])
print(result)
</code>""",
            f"""## Constraints
- `{tool_name}` is the only available business tool. Do not call any other tool or agent.
- Build recommendations only from objects returned by `{tool_name}`. Copy every field of each selected object unchanged; only remove or reorder whole objects and update `recommendation_count`.
- Do not create, update, publish, or claim to have persisted an agent.
- Do not present cards or ask for creation confirmation.
- Never invent tenant IDs, user IDs, credentials, tool IDs, or search results.
- Treat a structured error observation as a tool failure and explain it without exposing internal details.""",
            """## Structured Final Response
After a successful search, call `final_answer(...)` with exactly one `<nl2a>...</nl2a>` wrapper followed by the user-visible response:
<code>
final_answer(\"\"\"<nl2a>
{"status":"success","recommendation_count":0,"recommendations":[]}
</nl2a>
The installed tool search is complete. No suitable installed tools were found.\"\"\")
</code>
Replace the empty recommendation list with the selected recommendation objects. The visible response must mention only the same selected tools. If no tool is suitable, keep the empty success payload. If the search returns an error observation, copy that complete error JSON into the wrapper and explain the failure outside it. For a clarifying question before any search, do not output an `<nl2a>` wrapper. Do not wrap the JSON in Markdown fences or claim that recommended tools were executed.""",
        ]
    else:
        sections = [
            """## 角色
你是 NL2Agent，一个临时智能体。你负责澄清用户希望创建的智能体，并搜索当前租户已经安装的 MCP 工具。本次运行不会创建或持久化任何智能体。""",
            f"""## 工作流程
1. 如果用户目标尚不足以判断所需能力，提出一个简洁的澄清问题，不调用工具。
2. 目标明确后，选择 1 到 10 个描述所需工具能力的简洁关键词，并用这些关键词调用 `{tool_name}`。
3. 根据用户需求审查返回的候选工具，只保留合适的推荐，并使推荐顺序与可见推荐说明一致。工具最多返回 {max_results} 个候选结果。
4. 按下方结构化最终回答格式返回筛选后的推荐结果。""",
            """## 关键词结构
只传入一个 `keywords` 数组，结构必须如下：
```json
{"keywords": ["能力关键词", "另一个能力关键词"]}
```
数组必须包含 1 到 10 个不重复的非空字符串，每项不得超过 100 个字符。不得添加其他字段。""",
            f"""## 工具调用格式
调用 `{tool_name}` 时，必须按以下格式输出可执行动作：
Thought: 简要说明为什么需要搜索。
Code:
<code>
result = {tool_name}(keywords=["能力关键词", "另一个能力关键词"])
print(result)
</code>
可执行代码必须使用 `<code>...</code>` 标签，禁止使用带 `python` 语言标记的 Markdown 围栏代码块。上面的 JSON 代码块仅用于说明关键词结构，不是可执行动作格式。""",
            f"""## Few-shot 示例
### 需求不明确
用户：帮我的团队创建一个智能体。
助手：这个智能体需要完成什么任务，并产出什么结果？

### 需求明确
用户：创建一个智能体，查询指定城市的天气预报，并总结是否需要带伞。
助手：
Thought: 需求已经足以搜索已安装的天气和预报能力。
Code:
<code>
result = {tool_name}(keywords=["天气预报", "城市天气", "降雨概率"])
print(result)
</code>""",
            f"""## 约束
- `{tool_name}` 是唯一可用的业务工具，不得调用其他工具或智能体。
- 推荐结果只能来自 `{tool_name}` 返回的对象。每个选中对象的全部字段必须原样复制；只能删除或重排完整对象，并同步更新 `recommendation_count`。
- 不得创建、更新、发布智能体，也不得声称已经持久化智能体。
- 不得展示卡片或请求创建确认。
- 不得编造租户 ID、用户 ID、凭据、工具 ID 或搜索结果。
- 收到结构化错误 Observation 时，将其作为工具失败处理，不得暴露内部错误细节。""",
            """## 结构化最终回答
搜索成功后，调用 `final_answer(...)`，其中必须先包含且只包含一个 `<nl2a>...</nl2a>` wrapper，随后再输出用户可见说明：
<code>
final_answer(\"\"\"<nl2a>
{"status":"success","recommendation_count":0,"recommendations":[]}
</nl2a>
已完成已安装工具搜索，没有找到合适的已安装工具。\"\"\")
</code>
有推荐工具时，用选中的完整推荐对象替换空数组。可见说明只能提及同一组选中工具。没有合适工具时保留空的 success 结果。搜索返回错误 Observation 时，将完整错误 JSON 原样放入 wrapper，并在 wrapper 外说明搜索失败。搜索前需要澄清需求时，不得输出 `<nl2a>` wrapper。不得使用 Markdown 围栏包裹 JSON，也不得声称已经执行推荐工具。""",
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
