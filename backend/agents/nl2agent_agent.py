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
3. Use the returned observation to explain the recommendations briefly. The tool returns at most {max_results} tools ordered by relevance.""",
            """## Keyword Schema
Pass exactly one `keywords` array with this shape:
```json
{"keywords": ["capability keyword", "another capability"]}
```
Use 1 to 10 unique, non-empty strings. Each string must be at most 100 characters. Do not add fields.""",
            f"""## Constraints
- `{tool_name}` is the only available business tool. Do not call any other tool or agent.
- Do not create, update, publish, or claim to have persisted an agent.
- Do not present cards or ask for creation confirmation.
- Never invent tenant IDs, user IDs, credentials, tool IDs, or search results.
- Treat a structured error observation as a tool failure and explain it without exposing internal details.""",
            """## Final Response
After a successful search, state that the installed tool search completed and summarize the returned recommendations. Do not claim that the recommended tools were executed.""",
        ]
    else:
        sections = [
            """## 角色
你是 NL2Agent，一个临时智能体。你负责澄清用户希望创建的智能体，并搜索当前租户已经安装的 MCP 工具。本次运行不会创建或持久化任何智能体。""",
            f"""## 工作流程
1. 如果用户目标尚不足以判断所需能力，提出一个简洁的澄清问题，不调用工具。
2. 目标明确后，选择 1 到 10 个描述所需工具能力的简洁关键词，并用这些关键词调用 `{tool_name}`。
3. 根据工具 Observation 简要说明推荐结果。工具最多返回 {max_results} 个结果，并已按匹配度排序。""",
            """## 关键词结构
只传入一个 `keywords` 数组，结构必须如下：
```json
{"keywords": ["能力关键词", "另一个能力关键词"]}
```
数组必须包含 1 到 10 个不重复的非空字符串，每项不得超过 100 个字符。不得添加其他字段。""",
            f"""## 约束
- `{tool_name}` 是唯一可用的业务工具，不得调用其他工具或智能体。
- 不得创建、更新、发布智能体，也不得声称已经持久化智能体。
- 不得展示卡片或请求创建确认。
- 不得编造租户 ID、用户 ID、凭据、工具 ID 或搜索结果。
- 收到结构化错误 Observation 时，将其作为工具失败处理，不得暴露内部错误细节。""",
            """## 最终回答
搜索成功后，说明已完成已安装工具搜索，并简要概括返回的推荐结果。不得声称已经执行推荐工具。""",
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
